#!/usr/bin/env python3
"""
Builds the JSON documentation that is published with every release.

The document is written in two passes, because this package has two public surfaces and
neither one describes the other.

The first pass is Griffe reading the source statically, without importing it. It walks
every module that declares `__all__` and documents the names it finds, producing the
Python reference: the settings, the result models, the errors, the middleware. What it
writes is a distilled view under a schema this repository owns rather than the internal
Griffe model, which avoids internal details that change between Griffe versions.

The second pass builds the server and reads it. It exists because the tools are nested
functions inside their `register()` call, and Griffe does not descend into function
bodies, so the ten tools an agent actually calls are invisible to a static read. This
pass imports the package, and it is the only part that does.

Example:
    ```bash
    uv sync --group docs
    uv run python scripts/build_docs.py --strict
    ```
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from datetime import datetime, timezone
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

import griffe
from griffe import ParameterKind

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: Python 3.10, where tomli is the backport
    import tomli as tomllib  # type: ignore[no-redef]

#: Bump whenever a field in the emitted document changes meaning or disappears. This
#: numbering belongs to this repository; the client's document has its own.
SCHEMA_VERSION = 2

#: Attribute values longer than this are truncated; some public constants are large.
MAX_VALUE_CHARS = 2000

#: Admonition kinds that read as usage examples rather than asides.
EXAMPLE_KINDS = frozenset({"example", "examples"})

#: Annotations whose first type argument is what a caller receives, not the annotation
#: itself. Used to describe what a generator or context manager yields.
ITERATOR_TYPES = frozenset(
    {
        "Iterator",
        "Iterable",
        "Generator",
        "AsyncIterator",
        "AsyncIterable",
        "AsyncGenerator",
    }
)

ROOT = Path(__file__).resolve().parent.parent

#: Where the document lands unless `--output` says otherwise. Relative to the repository
#: root, so the command works from any directory.
DEFAULT_OUTPUT = ROOT / "docs" / "docs.json"


def read_project() -> Tuple[str, str, str, Path]:
    """
    Read the distribution name, version, import name, and source root.

    Returns:
        The distribution name, the version, the import name, and the directory to hand
        Griffe as a search path. The import name is derived from the wheel package
        declaration rather than guessed from the distribution name.
    """
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    packages = data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    if len(packages) != 1:
        raise SystemExit(
            "Expected exactly one entry in [tool.hatch.build.targets.wheel] packages, "
            f"found {packages!r}. This script documents a single package."
        )
    search_path, _, import_name = packages[0].rpartition("/")
    return project["name"], project["version"], import_name, ROOT / search_path


def load_package(import_name: str, search_path: Path) -> Any:
    """
    Load the package with Griffe statically and without importing it.

    Args:
        import_name: The top-level module to load.
        search_path: The directory the module lives in.

    Returns:
        The loaded module.
    """
    # Griffe logs a warning for every alias it cannot resolve, and the standard library
    # and third-party annotations produce plenty. They are not actionable here.
    logging.getLogger("griffe").setLevel(logging.ERROR)
    return griffe.load(
        import_name,
        search_paths=[search_path],
        docstring_parser=griffe.Parser.google,
        resolve_aliases=True,
        resolve_external=False,
        allow_inspection=False,
    )


def comment_docstring(obj: Any) -> Optional[str]:
    """
    Recover the comment written above a module attribute.

    Griffe only treats a string literal following an assignment as that attribute
    docstring. This codebase documents its public constants with the Sphinx-style
    comment instead. Without this those would otherwise arrive undocumented.

    Args:
        obj: The attribute to look above.

    Returns:
        The joined comment text, or `None` when there is no such comment.
    """
    lines = getattr(obj, "lines_collection", None)
    if lines is None or obj.filepath is None or obj.lineno is None:
        return None
    try:
        source = lines[obj.filepath]
    except KeyError:
        return None

    collected: List[str] = []
    index = obj.lineno - 2  # `lineno` is 1-based, so this is the line above.
    while index >= 0:
        line = source[index].strip()
        if not line.startswith("#:"):
            break
        collected.append(line[2:].strip())
        index -= 1
    return " ".join(reversed(collected)) or None


def split_summary(text: str) -> Tuple[str, str]:
    """
    Split docstring prose into its first paragraph and the rest.

    Args:
        text: The joined text of the docstring.

    Returns:
        The summary and the remaining description. Either of these may be empty.
    """
    stripped = text.strip()
    if not stripped:
        return "", ""
    head, _, tail = stripped.partition("\n\n")
    return " ".join(head.split()), unwrap(tail)


def unwrap(text: str) -> str:
    """
    Drop the line breaks that only exist to keep the source within 88 columns.

    Docstrings are wrapped to the line length the formatter enforces. This is a property
    of the source file and not of the prose. A consumer rendering this document wants
    paragraphs it can reflow so the soft breaks are removed while the real structure
    stays intact. Blank lines still separate paragraphs and any paragraph containing an
    indented line is left exactly as written because the indentation carries meaning
    that collapsing would destroy.

    Args:
        text: The raw description.

    Returns:
        The same text with soft wrapping removed.
    """
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        if re.search(r"^\s+\S", paragraph, re.MULTILINE):
            paragraphs.append(paragraph.strip("\n"))
        else:
            paragraphs.append(" ".join(paragraph.split()))
    return "\n\n".join(part for part in paragraphs if part)


def join_wrapped(descriptions: List[str]) -> str:
    """
    Rejoin a description the Google parser split across several entries.

    A return block with no name is one wrapped paragraph but the parser reads every line
    at the same indentation as a separate return value. Joining them back restores the
    sentence the author originally wrote.

    Args:
        descriptions: The per-entry descriptions in order.

    Returns:
        One paragraph.
    """
    return re.sub(r"\s+", " ", " ".join(descriptions)).strip()


def read_sections(docstring: Any) -> Dict[str, Any]:
    """
    Reduce a parsed docstring to the pieces this schema carries.

    Args:
        docstring: The Griffe docstring, or `None`.

    Returns:
        A mapping with the text, parameters, returns, yields, raises, attributes,
        examples, and notes found. Absent sections come back empty rather than missing.
    """
    found: Dict[str, Any] = {
        "text": "",
        "parameters": {},
        "returns": [],
        "yields": [],
        "raises": [],
        "attributes": {},
        "examples": [],
        "notes": [],
    }
    if docstring is None:
        return found

    texts: List[str] = []
    for section in docstring.parsed:
        kind = section.kind.value
        if kind == "text":
            texts.append(section.value)
        elif kind == "parameters":
            for item in section.value:
                found["parameters"][item.name] = unwrap(item.description)
        elif kind == "returns":
            found["returns"] = list(section.value)
        elif kind == "yields":
            found["yields"] = list(section.value)
        elif kind == "raises":
            for item in section.value:
                found["raises"].append(
                    {
                        "annotation": str(item.annotation) if item.annotation else None,
                        "description": unwrap(item.description),
                    }
                )
        elif kind == "attributes":
            for item in section.value:
                found["attributes"][item.name] = {
                    "annotation": str(item.annotation) if item.annotation else None,
                    "description": unwrap(item.description),
                }
        elif kind == "examples":
            found["examples"].append(str(section.value).strip())
        elif kind == "admonition":
            admonition = section.value
            if admonition.kind in EXAMPLE_KINDS:
                found["examples"].append(admonition.contents.strip())
            else:
                found["notes"].append(
                    {
                        "title": section.title or admonition.kind,
                        "text": unwrap(admonition.contents),
                    }
                )

    found["text"] = "\n\n".join(part.strip() for part in texts if part.strip())
    return found


def read_returns(func: Any, sections: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Describe what a function returns from its annotation and docstring.

    Args:
        func: The Griffe function.
        sections: The output of `read_sections` for that function.

    Returns:
        The return annotation and description, or `None` when there is neither.
    """
    annotation = str(func.returns) if getattr(func, "returns", None) else None
    items = sections["returns"]

    if items and all(not item.name for item in items):
        # One wrapped paragraph the parser split by line.
        description = join_wrapped([item.description for item in items])
        if not annotation and items[0].annotation:
            annotation = str(items[0].annotation)
        values = None
    elif items:
        # Genuinely several documented values, so keep them apart.
        description = ""
        values = [
            {
                "name": item.name or None,
                "annotation": str(item.annotation) if item.annotation else None,
                "description": unwrap(item.description),
            }
            for item in items
        ]
    else:
        description = ""
        values = None

    if not annotation and not description and not values:
        return None

    returns: Dict[str, Any] = {"annotation": annotation, "description": description}
    if values:
        returns["values"] = values
    return returns


def yielded_type(annotation: Optional[str]) -> Optional[str]:
    """
    Reduce an iterator annotation to the type a caller actually receives.

    Griffe fills a yield item's annotation in from the function's return type when the
    docstring does not spell one out, which leaves `AsyncIterator[GuardClientHandle]`
    sitting where `GuardClientHandle` belongs.

    Args:
        annotation: The rendered annotation, which may be `None`.

    Returns:
        The first type argument of a recognised iterator wrapper, or the annotation
        unchanged when it is not one.
    """
    if not annotation or "[" not in annotation or not annotation.endswith("]"):
        return annotation
    head, _, rest = annotation.partition("[")
    if head.rpartition(".")[2] not in ITERATOR_TYPES:
        return annotation

    # Split on the first top-level comma, so `Generator[X, None, None]` gives `X` and a
    # nested `AsyncIterator[Dict[str, Any]]` is not cut inside its own brackets.
    inner = rest[:-1]
    depth = 0
    for index, char in enumerate(inner):
        if char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
        elif char == "," and depth == 0:
            return inner[:index].strip()
    return inner.strip()


def read_yields(sections: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Describe what a generator or context manager yields.

    This is kept apart from the return annotation on purpose. `guard_client` is
    annotated `AsyncIterator[GuardClientHandle]` but yields a `GuardClientHandle`, and
    reporting the wrapper as the thing a caller receives would be a lie about the API.
    A reader wants to know what arrives inside the `async with`.

    Args:
        sections: The output of `read_sections` for that function.

    Returns:
        The yielded annotation and description, or `None` when nothing was documented.
    """
    items = sections["yields"]
    if not items:
        return None

    if all(not item.name for item in items):
        # One wrapped paragraph the parser split by line.
        raw = str(items[0].annotation) if items[0].annotation else None
        return {
            "annotation": yielded_type(raw),
            "description": join_wrapped([item.description for item in items]),
        }
    return {
        "annotation": None,
        "description": "",
        "values": [
            {
                "name": item.name or None,
                "annotation": str(item.annotation) if item.annotation else None,
                "description": unwrap(item.description),
            }
            for item in items
        ],
    }


def visible_parameters(func: Any) -> List[Any]:
    """
    Drop the bound receiver from the parameters of a method.

    Args:
        func: The Griffe function.

    Returns:
        Every parameter a caller actually passes.
    """
    parameters = list(func.parameters)
    if parameters and parameters[0].name in {"self", "cls"}:
        return parameters[1:]
    return parameters


def render_signature(func: Any) -> str:
    """
    Render a call signature the way it would be written in source.

    Args:
        func: The Griffe function.

    Returns:
        The signature including annotations, defaults, and the return type.
    """
    parts: List[str] = []
    star_written = False
    parameters = visible_parameters(func)

    for index, param in enumerate(parameters):
        if param.kind is ParameterKind.var_positional:
            star_written = True
            parts.append(f"*{param.name}")
            continue
        if param.kind is ParameterKind.var_keyword:
            parts.append(f"**{param.name}")
            continue
        if param.kind is ParameterKind.keyword_only and not star_written:
            parts.append("*")
            star_written = True

        rendered = param.name
        if param.annotation is not None:
            rendered += f": {param.annotation}"
        if param.default is not None:
            rendered += (
                f" = {param.default}" if param.annotation else f"={param.default}"
            )
        parts.append(rendered)

        following = parameters[index + 1 :]
        if param.kind is ParameterKind.positional_only and not any(
            other.kind is ParameterKind.positional_only for other in following
        ):
            parts.append("/")

    returns = f" -> {func.returns}" if getattr(func, "returns", None) else ""
    return f"({', '.join(parts)}){returns}"


def document_parameters(func: Any, described: Dict[str, str]) -> List[Dict[str, Any]]:
    """
    Pair each parameter in the signature with its documented description.

    Args:
        func: The Griffe function.
        described: Descriptions keyed by parameter name.

    Returns:
        One entry per parameter in signature order. The annotation, default, and kind
        come from the signature. This ensures a docstring that repeats the type cannot
        contradict the code.
    """
    documented: List[Dict[str, Any]] = []
    for param in visible_parameters(func):
        documented.append(
            {
                "name": param.name,
                "annotation": str(param.annotation) if param.annotation else None,
                "default": str(param.default) if param.default is not None else None,
                "kind": param.kind.value,
                "description": described.get(param.name, ""),
            }
        )
    return documented


def truncate(value: str) -> Tuple[str, bool]:
    """
    Cap an attribute value so one large constant cannot dominate the document.

    Args:
        value: The rendered value.

    Returns:
        The value and whether it was shortened.
    """
    if len(value) <= MAX_VALUE_CHARS:
        return value, False
    return value[:MAX_VALUE_CHARS] + " ...", True


def source_of(obj: Any) -> Dict[str, Any]:
    """
    Locate an object in the repository.

    Args:
        obj: The Griffe object.

    Returns:
        The defining module, its path relative to the repository root, and the line
        number. The absolute path is deliberately omitted because it would publish the
        layout of whichever machine built the release.
    """
    return {
        "module": obj.module.path if obj.parent else obj.path,
        "relative_filepath": str(obj.relative_filepath) if obj.filepath else None,
        "lineno": obj.lineno,
    }


def document_function(func: Any, path: str) -> Dict[str, Any]:
    """
    Describe a function or method.

    Args:
        func: The Griffe function.
        path: The public dotted path callers reach it by.

    Returns:
        The documented function.
    """
    sections = read_sections(func.docstring)
    summary, description = split_summary(sections["text"])

    documented: Dict[str, Any] = {
        "name": func.name,
        "path": path,
        "canonical_path": func.canonical_path,
        "kind": "function",
        "summary": summary,
        "description": description,
        "signature": render_signature(func),
        "parameters": document_parameters(func, sections["parameters"]),
        "returns": read_returns(func, sections),
        "yields": read_yields(sections),
        "raises": sections["raises"],
        "examples": sections["examples"],
        "notes": sections["notes"],
        "source": source_of(func),
    }
    if func.decorators:
        documented["decorators"] = [str(item.value) for item in func.decorators]
    return documented


def document_attribute(attribute: Any, path: str) -> Dict[str, Any]:
    """
    Describe a module-level or class-level constant.

    Args:
        attribute: The Griffe attribute.
        path: The public dotted path callers reach it by.

    Returns:
        The documented attribute including its value. This is frequently the
        documentation people actually want for a constant.
    """
    text = (
        attribute.docstring.value
        if attribute.docstring
        else comment_docstring(attribute)
    )
    summary, description = split_summary(text or "")

    documented: Dict[str, Any] = {
        "name": attribute.name,
        "path": path,
        "canonical_path": attribute.canonical_path,
        "kind": "attribute",
        "summary": summary,
        "description": description,
        "annotation": str(attribute.annotation) if attribute.annotation else None,
        "source": source_of(attribute),
    }
    if attribute.value is not None:
        value, truncated = truncate(str(attribute.value))
        documented["value"] = value
        documented["truncated"] = truncated
    return documented


def inherited_attributes(cls: Any, sections: Dict[str, Any]) -> Dict[str, Any]:
    """
    Collect the documented attributes of a class and everything it inherits from.

    For example, `SignalMatch` adds two fields to `Signal` and documents only those two.
    The other six are described on the base class. Reading the class alone would report
    them as undocumented.

    Args:
        cls: The Griffe class.
        sections: The output of `read_sections` for that class.

    Returns:
        Attribute entries keyed by name with the attributes of the class winning over
        the base classes.
    """
    collected: Dict[str, Any] = {}
    try:
        ancestors = list(reversed(cls.mro()))
    except Exception:  # noqa: BLE001 - an unresolved base is not worth failing over
        ancestors = []
    for ancestor in ancestors:
        collected.update(read_sections(ancestor.docstring)["attributes"])
    collected.update(sections["attributes"])
    return collected


def document_class(cls: Any, path: str) -> Dict[str, Any]:
    """
    Describe a class and fold its constructor into the class itself.

    Args:
        cls: The Griffe class.
        path: The public dotted path callers reach it by.

    Returns:
        The documented class. The constructor is not emitted as a member because its
        parameters are the class parameters which is where a reader looks for them. For
        a dataclass whose constructor is synthesised and carries no docstring, the
        parameter descriptions are taken from the class attributes section instead.

    Raises:
        KeyError: Never raised directly. Documented members are looked
            up defensively.
    """
    sections = read_sections(cls.docstring)
    summary, description = split_summary(sections["text"])
    bases = [str(base) for base in cls.bases]
    is_enum = any(base.split(".")[-1].endswith("Enum") for base in bases)

    documented: Dict[str, Any] = {
        "name": cls.name,
        "path": path,
        "canonical_path": cls.canonical_path,
        "kind": "class",
        "summary": summary,
        "description": description,
        "bases": bases,
        "is_enum": is_enum,
        "labels": sorted(cls.labels),
        "signature": "()",
        "parameters": [],
        "raises": sections["raises"],
        "examples": sections["examples"],
        "notes": sections["notes"],
        "attributes": [],
        "members": [],
        "source": source_of(cls),
    }

    constructor = cls.members.get("__init__")
    if constructor is not None and not constructor.is_alias:
        described = read_sections(constructor.docstring)
        # A synthesised dataclass constructor has no docstring of its own, so the
        # field descriptions live in the class's `Attributes:` section instead — and
        # for a subclass, the inherited fields are documented on the base.
        parameter_docs = described["parameters"] or {
            name: entry["description"]
            for name, entry in inherited_attributes(cls, sections).items()
        }
        documented["signature"] = render_signature(constructor).removesuffix(" -> None")
        documented["parameters"] = document_parameters(constructor, parameter_docs)
        documented["raises"] = described["raises"] or documented["raises"]
        if described["text"]:
            constructor_summary, constructor_description = split_summary(
                described["text"]
            )
            documented["constructor"] = {
                "summary": constructor_summary,
                "description": constructor_description,
            }

    for name, entry in inherited_attributes(cls, sections).items():
        documented["attributes"].append(
            {
                "name": name,
                "annotation": entry["annotation"],
                "description": entry["description"],
            }
        )

    for name, member in cls.members.items():
        if name.startswith("_"):
            continue
        target = resolve(member)
        if target is None:
            continue
        member_path = f"{path}.{name}"
        if target.kind is griffe.Kind.FUNCTION:
            documented["members"].append(document_function(target, member_path))
        elif target.kind is griffe.Kind.ATTRIBUTE and (
            is_enum or target.docstring or comment_docstring(target)
        ):
            # Undocumented class attributes are almost always dataclass fields, which
            # the `Attributes:` section above already covers. An enum is the exception:
            # its members are the whole point of it, and they carry their value rather
            # than a docstring.
            documented["members"].append(document_attribute(target, member_path))

    return documented


def resolve(obj: Any) -> Optional[Any]:
    """
    Follow an alias to the object it points at.

    Args:
        obj: A Griffe object or alias.

    Returns:
        The object itself, or `None` when the alias cannot be resolved. This happens for
        anything re-exported from outside the package.
    """
    if not obj.is_alias:
        return obj
    try:
        return obj.final_target
    except Exception:  # noqa: BLE001 - griffe raises several unrelated alias errors
        return None


def document(obj: Any, path: str) -> Optional[Dict[str, Any]]:
    """
    Describe any exported object.

    Args:
        obj: The Griffe object.
        path: The public dotted path callers reach it by.

    Returns:
        The documented object, or `None` for a kind this schema does not carry.
    """
    if obj.kind is griffe.Kind.CLASS:
        return document_class(obj, path)
    if obj.kind is griffe.Kind.FUNCTION:
        return document_function(obj, path)
    if obj.kind is griffe.Kind.ATTRIBUTE:
        return document_attribute(obj, path)
    return None


def check(documented: Dict[str, Any], problems: List[str], gaps: List[str]) -> None:
    """
    Complain about anything public that is not documented.

    This operates at two levels because they are not equally serious. A public object
    with no docstring at all is a hole in the reference and fails the strict check. A
    missing argument description is reported but never fatal. Methods on the async
    client deliberately carry a summary and cross-reference their synchronous twin
    instead of repeating nine argument descriptions.

    Args:
        documented: One documented object.
        problems: The list to append hard failures to.
        gaps: The list to append advisory findings to.
    """
    path = documented["path"]
    if not documented["summary"]:
        problems.append(f"{path} has no docstring")

    for parameter in documented.get("parameters", []):
        if parameter["kind"] in {"variadic positional", "variadic keyword"}:
            continue
        if not parameter["description"]:
            gaps.append(f"{path} does not document its `{parameter['name']}` argument")

    returns = documented.get("returns")
    if (
        returns
        and returns["annotation"] not in (None, "None")
        and not returns["description"]
        and "values" not in returns
        # A generator documents its output under `Yields:`, and that is the right
        # section for it. Demanding a `Returns:` as well would be asking for the
        # iterator wrapper to be described, which tells a caller nothing.
        and not documented.get("yields")
    ):
        gaps.append(f"{path} does not document what it returns")

    for member in documented.get("members", []):
        if documented.get("is_enum") and member["kind"] == "attribute":
            # An enum member documents itself: `Engine.LOCAL = "local"` says it all.
            continue
        check(member, problems, gaps)


def document_tool(tool: Any) -> Dict[str, Any]:
    """
    Describe one MCP tool as an agent is offered it.

    Args:
        tool: The FastMCP tool object.

    Returns:
        The tool's name, the description an agent reads, both JSON schemas, its
        behavioural annotations, and its background task declaration. The schemas are
        emitted verbatim: they are the contract, and paraphrasing them here would only
        create a second version of it to disagree with.
    """
    task = tool.task_config
    return {
        "name": tool.name,
        "title": tool.title,
        "description": tool.description or "",
        "input_schema": tool.parameters,
        "output_schema": tool.output_schema,
        "annotations": tool.annotations.model_dump(exclude_none=True)
        if tool.annotations
        else {},
        "tags": sorted(tool.tags),
        "task": {
            "mode": task.mode,
            "poll_interval_seconds": task.poll_interval.total_seconds()
            if task.poll_interval
            else None,
        }
        if task
        else None,
    }


def document_resource(resource: Any) -> Dict[str, Any]:
    """
    Describe one MCP resource.

    Args:
        resource: The FastMCP resource object.

    Returns:
        The URI an agent reads it by, its name, description and media type.
    """
    return {
        "uri": str(resource.uri),
        "name": resource.name,
        "description": resource.description or "",
        "mime_type": resource.mime_type,
        "tags": sorted(resource.tags),
    }


async def read_server() -> Dict[str, Any]:
    """
    Read the tools and resources off an assembled server.

    Returns:
        The server's own instructions, and its tools and resources sorted by name so a
        diff between two releases shows what changed rather than what moved.

    Note:
        The import is deliberately local. Everything above this point reads the source
        statically and works without the runtime dependencies installed; this function
        is the one place that imports the package, and keeping that import here means a
        failure to build the server cannot be mistaken for a failure to parse it.
    """
    from guard_mcp.server import create_server
    from guard_mcp.settings import GuardMCPSettings

    # Settings are pinned rather than read from the environment, because the surface
    # this documents has to be the one a reader gets by default. `enable_tasks` is the
    # setting that changes it: with tasks off, `analyze_media` reports the FastMCP
    # default of `forbidden` instead of the `optional` it actually declares. No API key
    # is needed or invented either; the client handle records the failure and
    # registration proceeds, which is the path `guard://config` exists to report.
    settings = GuardMCPSettings(_env_file=None, enable_tasks=True)
    server = create_server(settings)
    tools = await server.list_tools()
    resources = await server.list_resources()
    return {
        "instructions": server.instructions or "",
        "tools": [document_tool(tool) for tool in sorted(tools, key=lambda t: t.name)],
        "resources": [
            document_resource(resource)
            for resource in sorted(resources, key=lambda r: str(r.uri))
        ],
    }


def check_surface(
    surface: Dict[str, Any], problems: List[str], gaps: List[str]
) -> None:
    """
    Complain about anything in the served surface that is not documented.

    A tool description is not documentation in the usual sense: it is the only thing an
    agent reads before deciding to call it. An undocumented tool or argument is
    therefore treated exactly as harshly as an undocumented function.

    Args:
        surface: The output of `read_server`.
        problems: The list to append hard failures to.
        gaps: The list to append advisory findings to.
    """
    for tool in surface["tools"]:
        if not tool["description"]:
            problems.append(f"tool {tool['name']} has no description")
        for name, schema in tool["input_schema"].get("properties", {}).items():
            if not schema.get("description"):
                problems.append(
                    f"tool {tool['name']} does not document its `{name}` argument"
                )
        if not tool["output_schema"]:
            gaps.append(f"tool {tool['name']} declares no output schema")

    for resource in surface["resources"]:
        if not resource["description"]:
            problems.append(f"resource {resource['uri']} has no description")


def public_modules(module: Any) -> Iterator[Any]:
    """
    Yield the package and every submodule that declares `__all__`.

    The client is one flat namespace and its top-level `__all__` is the whole API. This
    package is not: `guard_mcp.__all__` names two things, and everything worth reading
    lives a level down in `settings`, `schemas`, `errors` and the rest. A module that
    writes `__all__` is declaring itself public, so that is the signal followed here
    rather than a list in this file that would drift.

    Args:
        module: The Griffe module to start from.

    Yields:
        Each module with a non-empty `__all__`, outermost first.
    """
    if module.exports:
        yield module
    for member in module.members.values():
        if member.kind is griffe.Kind.MODULE and not member.is_alias:
            yield from public_modules(member)


def build(
    surface: Optional[Dict[str, Any]] = None,
) -> Tuple[
    Dict[str, Any],
    List[str],
    List[str],
]:
    """
    Build the entire document.

    Args:
        surface: The MCP tools and resources read from the assembled server, or `None`
            when that pass was skipped.

    Returns:
        The document, the hard problems that fail the strict check, and the advisory
        gaps that are only ever reported.
    """
    name, package_version, import_name, search_path = read_project()
    package = load_package(import_name, search_path)

    problems: List[str] = []
    gaps: List[str] = []
    objects: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    for module in public_modules(package):
        for export in module.exports:
            export = str(export)
            if export.startswith("__"):
                # `__version__` and friends are metadata, not API.
                continue
            path = f"{module.path}.{export}"
            member = module.members.get(export)
            if member is None:
                problems.append(
                    f"{module.path}.__all__ names {export!r}, which does not exist"
                )
                continue
            target = resolve(member)
            if target is None:
                problems.append(f"{path} could not be resolved by griffe")
                continue
            if target.canonical_path in seen:
                # Re-exported, and already documented at the path it was first
                # reached by. Two entries for one object would only be two places
                # for the same text to be read.
                continue
            seen.add(target.canonical_path)
            documented = document(target, path)
            if documented is None:
                problems.append(
                    f"{path} is a {target.kind.value}, which this schema does not carry"
                )
                continue
            objects.append(documented)
            check(documented, problems, gaps)

    summary, _ = split_summary(package.docstring.value if package.docstring else "")
    document_out = {
        "schema_version": SCHEMA_VERSION,
        "package": name,
        "import_name": import_name,
        "version": package_version,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": {"tool": "griffe", "version": distribution_version("griffe")},
        "summary": summary,
        "objects": objects,
    }
    if surface is not None:
        document_out["mcp"] = surface
        check_surface(surface, problems, gaps)
    return document_out, problems, gaps


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"where to write the JSON document (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero when a public object has no docstring at all",
    )
    parser.add_argument(
        "--show-gaps",
        action="store_true",
        help="also list undocumented arguments and return values, which never fail",
    )
    parser.add_argument(
        "--no-server",
        action="store_true",
        help="skip the pass that builds the server, documenting only the Python API",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    surface = None if args.no_server else asyncio.run(read_server())
    documented, problems, gaps = build(surface)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(documented, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    # The default is an absolute path so the command works from any directory; report it
    # relative to the repository so the log line stays readable.
    written = args.output.resolve()
    if written.is_relative_to(ROOT):
        written = written.relative_to(ROOT)
    served = documented.get("mcp")
    print(
        f"Documented {len(documented['objects'])} public objects"
        + (
            f", {len(served['tools'])} tools and {len(served['resources'])} resources"
            if served
            else ""
        )
        + f" of {documented['package']} {documented['version']} -> {written}"
    )

    if gaps:
        print(f"{len(gaps)} arguments or return values are undocumented.")
        if args.show_gaps:
            for gap in gaps:
                print(f"  - {gap}")

    if problems:
        stream = sys.stderr if args.strict else sys.stdout
        print(f"\n{len(problems)} public objects are undocumented:", file=stream)
        for problem in problems:
            print(f"  - {problem}", file=stream)
        if args.strict:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

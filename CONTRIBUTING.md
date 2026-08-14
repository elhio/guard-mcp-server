# Contributing to the Guard

Thank you for considering contributing to Guard! We welcome contributions from everyone, whether it’s fixing bugs, 
adding new features, sharpening the ergonomics, or improving documentation.

The following is a set of guidelines for contributing to this repository.

## The Contributor License Agreement (CLA)

Before we can merge your first Pull Request, you will need to sign our Contributor License Agreement.

Don't worry, the process is fully automated! When you open your first Pull Request, our CLA bot will automatically 
comment on it with instructions. You will simply need to reply to that comment to sign the agreement. You only have to 
do this once.

This repository is licensed under the **Apache-2.0**, and your contributions are published under those terms. The 
optional on-device engine it can reach through the client, `guard-local-detector`, uses the AGPL-3.0 license and lives 
in its own repository. This difference is exactly why the local engine is an opt-in extra rather than a standard 
dependency.

## Getting Started

Before you start writing code, make sure your development environment is set up properly.

0. Fork the repository to your own GitHub account.

1. Install prerequisites: [uv](https://docs.astral.sh/uv/) and Python 3.10 or newer. You do not need to install Python 
yourself — uv will fetch a suitable interpreter.

2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/guard-mcp-server.git`

3. Sync the environment: `uv sync`

That last command creates a `.venv`, reads `uv.lock`, and installs the runtime and development dependencies exactly as 
they were locked. Nothing else is needed — the test suite is fully mocked, so there is no API key to obtain and no 
network access at any point.

## Branching Strategy

To keep the repository organized, please use descriptive branch names based on the type of work you are doing:

* **Features:** `feature/batch-analysis` or `feat/expose-runner-listing`
* **Bug Fixes:** `fix/symlink-path-check`
* **Documentation:** `docs/update-readme`

Always branch off of the `main` branch, and make sure your fork is up to date before starting new work.

## Development, Linting & Testing

Please ensure your changes pass all code quality checks and tests before opening a Pull Request.

### Code Quality & Types

Run the formatter, linter, and type-checker to ensure your code complies with our standards:

```bash
# format the code
uv run ruff format

# check for lint issues
uv run ruff check

# automatically fix lint issues where possible
uv run ruff check --fix

# check types (strict mode)
uv run mypy
```

Note that `ruff format` rewraps code but never touches comments or docstrings. If you still see an `E501` error, the 
long line is inside a comment or docstring and must be split manually.

### Running Tests

We use pytest. Please add or update tests whenever you introduce new features or fix bugs.

```bash
# run the whole suite
uv run pytest

# skip the subprocess test
uv run pytest -m "not slow"

# run one test with output
uv run pytest tests/test_media.py -v
```

Guard API calls are mocked with respx against [https://api.test.invalid](https://api.test.invalid), and every response 
comes from a builder in `tests/conftest.py` such as `create_response`, `detail_response` or `space_response`. If you 
add a new endpoint, add its builder there rather than committing a fixture. Media files are generated at run time by 
`png_bytes()` — please do not commit binaries. Async tests need no marker since `asyncio_mode` is set to `auto`.

An autouse fixture strips every `GUARD_*` variable and moves the working directory to a temp dir, so your real `.env` 
and API key can never leak into a test run. Please keep it that way.

### Building the Documentation

Every release publishes a JSON reference of this package, built by `scripts/build_docs.py` and checked in CI. Please 
run it before opening a Pull Request, because `--strict` is what the `lint` job runs and an undocumented public object 
or tool argument fails it.

```bash
# install griffe, once
uv sync --group docs

# build docs/docs.json, failing on anything undocumented
uv run python scripts/build_docs.py --strict

# also list undocumented arguments and return values, which never fail
uv run python scripts/build_docs.py --strict --show-gaps

# skip the pass that builds the server, when only the Python API matters
uv run python scripts/build_docs.py --no-server
```

The script makes two passes. The first is Griffe reading the source statically: it walks every module that declares 
`__all__` and documents the names in it, so exporting a name is what publishes it. The second builds the server and 
reads its tools and resources, which a static read cannot see — each tool is a nested function inside its `register()` 
call, and Griffe does not descend into function bodies. A tool's docstring is the description an agent reads before 
deciding to call it, so `--strict` treats a missing one exactly as harshly as an undocumented function.

`docs/docs.json` is git-ignored. It is a build artefact, rebuilt on every release and uploaded from CI.

### Testing against a Live API

To exercise the real lifecycle, point a client at the server with real credentials. **This runs against production by 
default and spends real tokens.** Use `GUARD_BASE_URL` to point elsewhere.

```bash
export GUARD_API_KEY=...   # a token_raw from POST /api/v1/tokens/
export GUARD_SPACE_ID=...
export GUARD_MCP_MEDIA_ROOTS=/path/to/media

# drive it by hand in the MCP Inspector
uv run fastmcp dev inspector guard_mcp -m

# or over stdio, the way a client will run it
uv run guard-mcp

# or over HTTP
uv run guard-mcp --transport http --port 9000

# on-device, which needs no key, no network and no tokens
GUARD_ENGINE=local uv run guard-mcp
```

Credentials resolve the same way everywhere: explicit arguments, then `GUARD_*` environment variables, then a `.env` 
file. Run `cp .env.example .env` and fill in your details instead of exporting variables if you prefer. The `.env` file 
is git-ignored and must stay that way. Please never put a real key in `.env.example`.

## What to Watch Out For

**The media path check is a security boundary.** `resolve_media_path` resolves symlinks *before* checking containment. 
Reversing that order would let a link inside an allowed directory read any file the server process can read. 
`tests/test_media.py` covers traversal, symlinks, directories and size; please extend it rather than working around it.

**Never make `guard-local-detector` a hard dependency.** It must stay an extra, and the `local` extra must point at 
`guard-client[local]` rather than the engine directly, so the client's lazy import and error translation stay in 
charge. Aside from the licensing difference, a hard dependency would drag an ONNX runtime into every install.

**Tool docstrings are prompts.** They are what a model reads before deciding whether and how to call a tool. Write them 
for that reader: say what the tool decides, what the arguments mean in its terms, and what it must not assume. The 
injected `handle` and `progress` parameters are deliberately left undocumented, which is why `D417` is disabled for 
`src/guard_mcp/tools/`.

**Every Guard error must become an actionable message.** `errors.py` maps the client's hierarchy to `ToolError` text 
that names the variable to set or the tool to call next. An agent that reads "unauthorized" retries; one that reads 
"set GUARD_API_KEY in the server environment" stops and tells the user. Add a case to `to_tool_error` and to 
`tests/test_errors.py` whenever the client grows an exception.

**A missing API key must not stop the server from starting.** `AsyncGuardClient` raises at construction when no key 
resolves. `guard_client()` catches that and reports it per tool call instead, because a client that cannot start the 
server shows the user nothing but "failed".

**`enable_tasks` gates two things at once.** FastMCP refuses to serve a tool declared with `task=` unless the tasks 
extension is registered, so the setting must control both the extension and the decorator. They are wired together in 
`create_server` and `tools/moderation.register`; changing one without the other makes the server fail to start.

**Background tasks cannot run inside the pytest event loop.** The Docket worker keeps a heartbeat scheduled after the 
MCP session ends, which pytest-asyncio waits on forever. That is why `tests/conftest.py` disables tasks and 
`tests/test_tasks.py` drives `tests/task_probe.py` as a subprocess instead. If you touch the task wiring, run that test.

**FastMCP 4 is a pre-release.** The pin in `pyproject.toml` is exact for a reason. Keep FastMCP-specific imports 
confined to `server.py`, `middleware.py` and the tool decorators, so a breaking change in a pre-release touches few 
files.

**Docstrings have a house style.** The summary goes on the line below the opening quotes and keeps that shape even when 
the body is one sentence (with `D200` and `D212` off, and `D213` on).

**`__all__` is the publish switch.** `scripts/build_docs.py` documents every name in every module's `__all__`, and 
`--strict` then demands a docstring for each one. Adding a name to `__all__` is therefore a decision to document and 
support it; leaving it out keeps it internal. Adding a new module with no `__all__` means nothing in it is published.

## Submitting a Pull Request

When you are ready to submit your code, open a Pull Request (PR) against the main branch of the original repository.

Please include the following in your PR description:

* **The Problem:** What issue does this PR solve? (Link to an existing Issue if applicable).
* **The Solution:** A brief explanation of how you solved it.
* **Testing:** How did you test your changes? Mention which tests were added, and whether you ran the suite with the 
`[local]` extra.
* **Tool surface impact:** If you added, renamed or changed the arguments of a tool, say so. That is a breaking change 
for every agent already using this server.

Once submitted, a maintainer will review your code. We may request some changes before merging, but we will always be 
respectful and constructive!

## Reporting Bugs & Requesting Features

If you aren't writing code but found a bug or have a feature idea, please open an Issue!

* Provide as much detail as possible, including your Python version, operating system, `guard_mcp.__version__`, and 
which MCP client you are using. The `guard-local-detector` version matters too, but only for `engine="local"` reports.
* Include what the `guard://config` resource reports. It is redacted and it answers most configuration questions 
immediately.
* For a failed request, include the full error text and the request id when one is quoted. Every `GuardAPIError` 
carries one, taken from the server's `x-request-id` header — it is the single most useful thing in a report, because it 
lets us find your exact request in our logs.
* If media was flagged incorrectly, please use `submit_feedback` on that result. That is the signal the platform learns 
from.

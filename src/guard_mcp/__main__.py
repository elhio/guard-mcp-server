"""
Entry point for `python -m guard_mcp`.

Equivalent to the `guard-mcp` console script. Both exist because MCP clients are
configured via command line, and some environments make it easier to point at a
module rather than a script that might not be on the system `PATH`.

Examples:
    ```bash
    python -m guard_mcp --transport http --port 9000
    ```
"""

from __future__ import annotations

from .server import main

if __name__ == "__main__":
    main()

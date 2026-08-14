<div align="center">
  <h1>
    <img src="https://raw.githubusercontent.com/elhio/guard-mcp-server/main/docs/guard.svg" width="100" alt="Guard Logo"><br>
    Guard
  </h1>
  <p><em>An MCP server that enables AI agents to analyze media for moderation via the Guard API</em></p>
  <p>
    <a href="https://pypi.org/project/guard-mcp-server/"><img src="https://img.shields.io/pypi/v/guard-mcp-server.svg?label=Release" alt="Release"></a>
    <a href="https://opensource.org/licenses/Apache-2.0"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License: Apache 2.0"></a>
    <a href="https://github.com/elhio/guard-mcp-server/fork"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome"></a>  
  </p>
</div>

## Features

**🛡️ Instant Content Moderation:** Ask your agent to analyze a file, and it will instantly identify AI-generated, 
violent, or explicit content in your images and videos.

**📸 One Core Tool:** The agent passes to the `analyze_media` tool a local file path and receives a list of detection 
tasks, each scored from 0 to 100. Because video analysis can take time, it runs as an MCP background task so your chat 
never freezes while waiting for results.

**🔒 Built-in Security Controls:** You have full control over what the agent can access. The server only reads media 
from directories you explicitly allow, ignores URL fetching, and enforces strict rate limits to protect your API budget 
from runaway or looping agents.

**🧰 Extended Tools & Resources:** Beyond basic analysis, your agent can fetch your exact workspace thresholds to apply 
your specific moderation rules, estimate token costs before processing large files, submit feedback on results, and 
read the server configuration to understand its environment

## Prerequisites

* **Python 3.10+**
* **uv:** This project uses [uv](https://docs.astral.sh/uv/) for fast package management.
* **Guard API Key:** You need an access token to use the Guard API. 
  * Already have one? You're good to go.
  * Need one? Create it for free in the [Elhio dashboard](https://elhio.com/settings/account).

## Installation

You can run the server directly via `uvx` or install it using `uv`:

```bash
# run it without installing
uvx guard-mcp-server

# or install it locally
uv pip install guard-mcp-server
```

### Claude Code

```bash
claude mcp add guard \
  --env GUARD_API_KEY=your-key \
  --env GUARD_SPACE_ID=your-space-id \
  --env GUARD_MCP_MEDIA_ROOTS=/path/to/your/media \
  -- uvx guard-mcp-server
```

### Claude Desktop, Cursor, and other JSON clients

Add the following to your MCP client configuration file (e.g., `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "guard": {
      "command": "uvx",
      "args": ["guard-mcp-server"],
      "env": {
        "GUARD_API_KEY": "your-key",
        "GUARD_SPACE_ID": "your-space-id",
        "GUARD_MCP_MEDIA_ROOTS": "/path/to/your/media"
      }
    }
  }
}
```

*Note: Set `GUARD_MCP_MEDIA_ROOTS` to the directories the agent may read media from. Without it, the server only accepts 
files under its own working directory, which is rarely where your images are.*

### Using the On-Device Engine

For local testing, development, or small open-source projects, you can install the optional on-device engine. It 
processes media entirely on your machine, requires no API key, and makes no network calls.

```bash
uv pip install "guard-mcp-server[local]"
```

Once installed, set `GUARD_ENGINE=local` to make it the default, or pass `engine: "local"` on a single analyze_media 
call.

*Note: While the main Guard MCP server is licensed under Apache 2.0, the optional `guard-local-detector` dependency is 
licensed under AGPL-3.0.*

## Usage

Once connected, you can ask your AI agent to moderate or analyze files on your system.

**Try asking your AI:**
* *"Analyze ~/Pictures/holiday.jpg and tell me what the models found."*
* *"Check ~/Downloads/news_photo.jpg. Does this look AI-generated?"*
* *"What models and predictors are available to my account?"*

### Example Workflow: Enforcing Workspace Policies

**👤 User**
> Check `~/Downloads/campaign_image.png`. Is this image AI-generated?

**🤖 Agent**
> *(Calls `analyze_media` and `get_space` to check your rules)*
> 
> I've analyzed the image. It received a score of 87/100 for the `AI-generated` detection task, which classifies it as 
> "Likely synthetic." Based on this high score, the model strongly indicates that this image was AI-generated rather 
> than being a real photograph.

A score runs from 0 to 100, where higher means more strongly detected. It is not a probability, and it is not a verdict 
— the API does not classify media, and neither does this server. To judge a score the way your product does, the agent 
will read `task_thresholds` from `get_space`: each detection task carries the `blur_threshold` and `hide_threshold` that 
space applies, either of which may be `null` when it does not police that task.

## Available Tools & Resources

The following tools are exposed by this server, allowing your AI agent to moderate content, check account 
configurations, and interact with the Guard platform.

* `analyze_media`: Analyze one image or video. Runs as a background task.
* `estimate_tokens`: Project the token cost of a file before spending it.
* `get_activity`: Fetch a stored activity and its scores, by id.
* `list_activities`: Page through recent activities.
* `list_spaces` / `get_space`: The spaces media can be analyzed in, and the cut-offs they apply.
* `list_detection_tasks`: The detection tasks the platform runs, with their ids.
* `list_predictors`: The models available to the account.
* `submit_feedback`: Report that a result was right or wrong.
* `share_result`: Create a link to one result that a person can open.

The following resources provide the AI agent with essential context about how the server and workspaces are currently 
configured.

* `guard://config`: View the currently resolved server configuration (API keys are redacted).
* `guard://spaces`: Exposes the available workspaces and their configuration.

## Configuration

Every setting is an environment variable, documented in [`.env.example`](.env.example). The core variables are:

| Variable | Default | Purpose |
| --- | --- | --- |
| `GUARD_API_KEY` | — | Required for the cloud engine. |
| `GUARD_SPACE_ID` | — | Default space to analyze in. |
| `GUARD_ENGINE` | `cloud` | `cloud` or `local`. |
| `GUARD_MCP_MEDIA_ROOTS` | working directory | Directories media may be read from, separated like `PATH`. |
| `GUARD_MCP_MAX_MEDIA_BYTES` | `104857600` | Largest accepted file. |
| `GUARD_MCP_ACTIVITY_REQUESTS_PER_MINUTE` | `30` | Budget for the billable tools. |
| `GUARD_MCP_ENABLE_TASKS` | `true` | Run `analyze_media` as a background task. |
| `GUARD_MCP_DOCKET_URL` | `memory://` | Task backend. Use Redis for multi-worker HTTP. |

### Running over HTTP

```bash
guard-mcp --transport http --host 0.0.0.0 --port 9000
```

The default `memory://` task backend keeps task state inside one process. Behind more than one worker, point 
`GUARD_MCP_DOCKET_URL` at Redis, or a task started on one worker will be invisible to the next request. 
`GUARD_MCP_DOCKET_NAME` and `GUARD_MCP_DOCKET_CONCURRENCY` set the queue name and the per-worker concurrency.

*Note: FastMCP reads the same three as `FASTMCP_DOCKET_URL`, `FASTMCP_DOCKET_NAME`, etc. Both spellings work and
the `GUARD_MCP_` one wins.*

## Development

This project uses [uv](https://docs.astral.sh/uv/) for package and environment management. A single `uv sync` creates the `.venv`, reads 
`uv.lock`, and installs everything exactly as it was locked. The test suite is fully mocked, so there is no API key to 
obtain and no network access at any point.

```bash
# set up the environment
uv sync --all-extras

# try it by hand
uv run fastmcp dev src/guard_mcp/server.py

# build for production
uv build
```

The [Contributing Guide](https://github.com/elhio/guard-mcp-server/blob/main/CONTRIBUTING.md) covers the rest: linting 
and type checking, the documentation build, working against the optional local engine, and testing end-to-end against 
a live API.

## Contributing

We welcome contributions! Please note that all contributors must sign our automated CLA. Read more in our 
[Contributing Guide](https://github.com/elhio/guard-mcp-server/blob/main/CONTRIBUTING.md).

## License

This repository and its corresponding PyPI package are licensed under the Apache v2.0 (Apache-2.0) - see the 
[LICENSE](https://github.com/elhio/guard-mcp-server/blob/main/LICENSE) file for details. 

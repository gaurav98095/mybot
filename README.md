# mybot

CLI chatbot powered by Claude. Supports tool use, web search, background subagents, and any MCP server.

## Install

```bash
pip install -e .
```

## Setup

```bash
mybot onboard           # creates ~/.mybot/config.json
```

Add your Anthropic API key to `~/.mybot/config.json`:

```json
{
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-..."
    }
  }
}
```

## Usage

```bash
mybot ask               # interactive REPL
mybot ask -m "Hello"    # single message
mybot ask --logs        # show runtime logs
```

## Tools

| Tool | Description |
|---|---|
| `shell` | Run shell commands |
| `web_search` | Search the web (DuckDuckGo by default) |
| `subagent` | Spawn background subagents for parallel tasks |
| `mcp_<server>__<tool>` | Any tool exposed by a configured MCP server |

### Web search providers

Set `tools.web.search.provider` in config. Options: `duckduckgo` (default, no key), `tavily`, `brave`, `searxng`, `jina`, `kagi`.

```json
{
  "tools": {
    "web": {
      "search": { "provider": "brave", "apiKey": "..." }
    }
  }
}
```

## MCP Servers

Add any MCP server under `mcp.servers` in config. Supported transports: `stdio`, `sse`, `http`.

```json
{
  "mcp": {
    "servers": {
      "filesystem": {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
      },
      "my-api": {
        "type": "sse",
        "url": "http://localhost:8000/sse"
      },
      "remote": {
        "type": "http",
        "url": "http://localhost:9000/mcp",
        "headers": { "Authorization": "Bearer sk-..." }
      }
    }
  }
}
```

All tools advertised by each server are discovered at startup and registered as `mcp_<server_id>__<tool_name>`. The agent can call them like any built-in tool.

## Tracing (Arize Phoenix)

```bash
mybot phoenix start     # spins up Phoenix via Docker on :6006
mybot phoenix stop
```

Enable in config, then open `http://localhost:6006`:

```json
{ "phoenix": { "enabled": true } }
```

Each user message is traced as a separate session with all LLM calls and tool executions nested inside.

## Pre-turn Classifier

Automatically route each message to the cheapest model that can handle it. Disabled by default.

```json
{
  "classifier": {
    "enabled": true,
    "classifierModel": "anthropic/claude-haiku-4-5-20251001",
    "simpleModel":     "anthropic/claude-haiku-4-5-20251001",
    "mediumModel":     "anthropic/claude-sonnet-4-6",
    "complexModel":    "anthropic/claude-opus-4-5"
  }
}
```

A single cheap LLM call classifies each message as `simple`, `medium`, or `complex` before the main turn. The selected tier model is used for that turn.

## Prompt Templates

All prompts live in `templates/<usecase>/<name>.md` and are loaded at import time via `mybot/templates.py`. To customise a prompt, edit the relevant `.md` file — no Python changes needed. Override the templates directory with the `MYBOT_TEMPLATES_DIR` environment variable.

## Config

Full config path: `~/.mybot/config.json`. All fields can be overridden via env vars prefixed `MYBOT_` with `__` as delimiter — e.g. `MYBOT_PROVIDERS__ANTHROPIC__API_KEY`.

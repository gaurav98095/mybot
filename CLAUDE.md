# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup & Running

```bash
pip install -e .                    # install in editable mode (includes tracing deps)
mybot onboard                       # create ~/.mybot/config.json (add API key after)
mybot onboard --workdir <path>      # also set custom agent workspace directory
mybot ask                           # interactive chat (REPL)
mybot ask -m "Hello"                # single-message mode
mybot ask --logs                    # show runtime logs during chat
mybot phoenix start                 # start Arize Phoenix tracing container (Docker)
mybot phoenix stop                  # stop Phoenix container
```

Config lives at `~/.mybot/config.json`. All config fields can be overridden via env vars prefixed `MYBOT_` with `__` as nested delimiter (e.g. `MYBOT_PROVIDERS__ANTHROPIC__API_KEY`).

Interactive REPL history is persisted (see `mybot/config/paths.py` for the path). The stream idle timeout defaults to 90 s and can be overridden with `MYBOT_STREAM_IDLE_TIMEOUT_S`.

Run the test suite with `pytest` (or `./run_tests.sh`). Tests live in `tests/`.

## Architecture

The project is a multi-provider LLM chatbot framework built around an async message bus.

**Data flow:**
```
CLI / Channel  →  MessageBus.inbound  →  AgentLoop  →  AgentRunner  →  LLMProvider
                                      ←  MessageBus.outbound  ←
```

**Key layers:**

- **`cli/commands.py`** — Typer app with `onboard`, `ask`, and `phoenix` (start/stop) commands. `ask` drives the interactive REPL: publishes `InboundMessage` to the bus, consumes `OutboundMessage`. Calls `setup_tracing()` on startup if Phoenix is enabled. MCP servers are started here (inside the `asyncio.run()` block) and stopped in a `finally`.

- **`cli/stream.py`** — Rich-based streaming UI. `ThinkingSpinner` wraps a Rich status spinner with pause support. `StreamRenderer` uses `Rich.Live` (auto_refresh=False) to render markdown deltas without flicker.

- **`bus/`** — `MessageBus` is two `asyncio.Queue`s (inbound/outbound). `InboundMessage` carries channel/sender/chat IDs and content; `OutboundMessage` carries the reply.

- **`agent/loop.py`** — `AgentLoop` drains `inbound` with a 1-second timeout and calls `_process_message`. Each user turn is wrapped in an OpenTelemetry `agent.turn` AGENT span (no-op when tracing is disabled). Accepts `extra_tools` to append tools (e.g. MCP proxy tools) on top of the defaults (`shell`, `web_search`, `subagent`).

- **`agent/runner.py`** — `AgentRunner` calls `provider.chat_with_retry()` and handles the tool-call loop (up to `MAX_TOOL_ROUNDS=10`). Each tool execution is wrapped in a `tool.<name>` TOOL span.

- **`agent/tools/`** — Tool registry + built-in tools:
  - `ShellTool` — runs shell commands via `asyncio.create_subprocess_shell`
  - `WebSearchTool` — web search with pluggable backends: `duckduckgo` (default), `tavily`, `brave`, `searxng`, `jina`, `kagi`
  - `SubagentTool` — spawns background `AgentRunner` tasks; actions: `spawn`, `result`, `list`. Subagents get `shell` + `web_search` but not another `SubagentTool` (prevents recursion).
  - `MCPProxyTool` / `MCPClient` / `MCPManager` (`mcp.py`) — connects to MCP servers and wraps each advertised tool as an `MCPProxyTool`. Names are `mcp_<server_id>__<tool_name>`. The transport context is held open in a background asyncio task for the lifetime of the run.

- **`agent/classifier.py`** — `PreTurnClassifier` runs a single cheap LLM call before each user turn to classify the task as `simple` / `medium` / `complex`, then returns the model name configured for that tier. Disabled by default (`classifier.enabled = false`). When enabled, `AgentLoop` instantiates it and passes the selected model to `AgentRunner.run(model=...)`.

- **`templates/`** — All prompt strings live here as `templates/<usecase>/<name>.md`. Loaded via `mybot/templates.py` (`load(usecase, name)` — `lru_cache`d). The project root is found by walking up from `__file__` until `pyproject.toml` is found; override with `MYBOT_TEMPLATES_DIR`. Current templates:
  - `classifier/system.md` — one-shot classification prompt (simple/medium/complex)
  - `tools/shell.md`, `tools/web_search.md`, `tools/subagent.md` — tool descriptions

- **`providers/base.py`** — `LLMProvider` ABC with retry logic (standard 3-attempt backoff + persistent mode), transient-error detection, Retry-After header parsing, and image-stripping fallback.

- **`providers/anthropic.py`** — Converts OpenAI-style message dicts to Anthropic Messages API format, handles prompt caching (`cache_control`), extended thinking (`reasoning_effort`: `adaptive` | `low` | `medium` | `high`), tool-call format, and streaming. `adaptive` lets the model decide when to think; `low/medium/high` set token budgets (1024 / 4096 / max). `claude-opus-4-7` rejects the `temperature` parameter entirely — the provider strips it automatically for that model.

- **`config/schema.py`** — Pydantic `Config` root with: `agents`, `providers` (anthropic only), `tools` (web search config + `tools.web.proxy` for HTTP/SOCKS5 proxy), `phoenix` (tracing config), `mcp` (MCP server config), `classifier` (pre-turn classifier config). Supports camelCase ↔ snake_case via `alias_generator=to_camel`. Default model is `anthropic/claude-opus-4-5`; the `anthropic/` prefix is stripped before the API call.

- **`config/loader.py`** — Load/save `Config` as JSON. Default path: `~/.mybot/config.json`.

- **`telemetry.py`** — `setup_tracing(config)` initialises the global OTel tracer provider pointed at Phoenix and auto-instruments the Anthropic SDK via `openinference`. No-ops when `phoenix.enabled = false` or packages are missing.

## MCP servers

Configured under `mcp.servers` in config. Each entry needs a `type` (`stdio`, `sse`, or `http`) plus transport-specific fields:

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

`MCPManager.start()` connects all servers concurrently at startup (30 s timeout per server; failures are logged and skipped). `get_all_tools()` returns the full flat list of `MCPProxyTool` instances passed to `AgentLoop` via `extra_tools`.

## Tracing

Phoenix traces are structured per user turn:
```
agent.turn [AGENT]  session.id=<uuid>  input/output
├── anthropic.messages.create [LLM]   ← auto-instrumented
├── tool.<name> [TOOL]                ← one span per tool call
└── anthropic.messages.create [LLM]  ← follow-up after tool results
```

Enable with `phoenix.enabled = true` in config after running `mybot phoenix start`.

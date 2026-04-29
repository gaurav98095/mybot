# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup & Running

```bash
pip install -e .          # install in editable mode (includes tracing deps)
mybot onboard             # create ~/.mybot/config.json (add API key after)
mybot ask                 # interactive chat (REPL)
mybot ask -m "Hello"      # single-message mode
mybot ask --logs          # show runtime logs during chat
mybot phoenix start       # start Arize Phoenix tracing container (Docker)
mybot phoenix stop        # stop Phoenix container
```

Config lives at `~/.mybot/config.json`. All config fields can be overridden via env vars prefixed `MYBOT_` with `__` as nested delimiter (e.g. `MYBOT_PROVIDERS__ANTHROPIC__API_KEY`).

## Architecture

The project is a multi-provider LLM chatbot framework built around an async message bus.

**Data flow:**
```
CLI / Channel  →  MessageBus.inbound  →  AgentLoop  →  AgentRunner  →  LLMProvider
                                      ←  MessageBus.outbound  ←
```

**Key layers:**

- **`cli/commands.py`** — Typer app with `onboard`, `ask`, and `phoenix` (start/stop) commands. `ask` drives the interactive REPL: publishes `InboundMessage` to the bus, consumes `OutboundMessage`. Calls `setup_tracing()` on startup if Phoenix is enabled.

- **`cli/stream.py`** — Rich-based streaming UI. `ThinkingSpinner` wraps a Rich status spinner with pause support. `StreamRenderer` uses `Rich.Live` (auto_refresh=False) to render markdown deltas without flicker.

- **`bus/`** — `MessageBus` is two `asyncio.Queue`s (inbound/outbound). `InboundMessage` carries channel/sender/chat IDs and content; `OutboundMessage` carries the reply.

- **`agent/loop.py`** — `AgentLoop` drains `inbound` with a 1-second timeout and calls `_process_message`. Each user turn is wrapped in an OpenTelemetry `agent.turn` AGENT span (no-op when tracing is disabled). Default tools: `shell`, `web_search`, `subagent`.

- **`agent/runner.py`** — `AgentRunner` calls `provider.chat_with_retry()` and handles the tool-call loop (up to `MAX_TOOL_ROUNDS=10`). Each tool execution is wrapped in a `tool.<name>` TOOL span.

- **`agent/tools/`** — Tool registry + three built-in tools:
  - `ShellTool` — runs shell commands via `asyncio.create_subprocess_shell`
  - `WebSearchTool` — web search with pluggable backends: `duckduckgo` (default), `tavily`, `brave`, `searxng`, `jina`, `kagi`
  - `SubagentTool` — spawns background `AgentRunner` tasks; actions: `spawn`, `result`, `list`. Subagents get `shell` + `web_search` but not another `SubagentTool` (prevents recursion).

- **`providers/base.py`** — `LLMProvider` ABC with retry logic (standard 3-attempt backoff + persistent mode), transient-error detection, Retry-After header parsing, and image-stripping fallback.

- **`providers/anthropic.py`** — Converts OpenAI-style message dicts to Anthropic Messages API format, handles prompt caching (`cache_control`), extended thinking (`reasoning_effort`), tool-call format, and streaming.

- **`config/schema.py`** — Pydantic `Config` root with: `agents`, `providers` (anthropic only), `tools` (web search config), `phoenix` (tracing config). Supports camelCase ↔ snake_case via `alias_generator=to_camel`.

- **`config/loader.py`** — Load/save `Config` as JSON. Default path: `~/.mybot/config.json`.

- **`telemetry.py`** — `setup_tracing(config)` initialises the global OTel tracer provider pointed at Phoenix and auto-instruments the Anthropic SDK via `openinference`. No-ops when `phoenix.enabled = false` or packages are missing.

## Tracing

Phoenix traces are structured per user turn:
```
agent.turn [AGENT]  session.id=<uuid>  input/output
├── anthropic.messages.create [LLM]   ← auto-instrumented
├── tool.<name> [TOOL]                ← one span per tool call
└── anthropic.messages.create [LLM]  ← follow-up after tool results
```

Enable with `phoenix.enabled = true` in config after running `mybot phoenix start`.

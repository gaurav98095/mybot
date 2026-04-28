# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup & Running

```bash
pip install -e .          # install in editable mode
mybot onboard             # create ~/.mybot/config.json (add API key after)
mybot ask                 # interactive chat (REPL)
mybot ask -m "Hello"      # single-message mode (not yet implemented)
mybot ask --logs          # show runtime logs during chat
```

Config lives at `~/.mybot/config.json`. All config fields can be overridden via env vars prefixed `MYBOT_` with `__` as nested delimiter (e.g. `MYBOT_AGENTS__DEFAULTS__MODEL`).

## Architecture

The project is a multi-provider LLM chatbot framework built around an async message bus.

**Data flow:**
```
CLI / Channel  →  MessageBus.inbound  →  AgentLoop  →  AgentRunner  →  LLMProvider
                                      ←  MessageBus.outbound  ←
```

**Key layers:**

- **`cli/commands.py`** — Typer app with two commands: `onboard` (writes config) and `ask` (drives the REPL). The REPL publishes `InboundMessage` to the bus and consumes `OutboundMessage` (stream chunks and final replies).

- **`cli/stream.py`** — Rich-based streaming UI. `ThinkingSpinner` wraps a Rich status spinner with pause support. `StreamRenderer` uses `Rich.Live` (auto_refresh=False) to render markdown deltas without flicker; it coexists with `prompt_toolkit` input by calling `stop_for_input()` before each prompt.

- **`bus/`** — `MessageBus` is two `asyncio.Queue`s (inbound/outbound). `InboundMessage` carries channel/sender/chat IDs and content; `OutboundMessage` carries the reply. The bus decouples channels from the agent core.

- **`agent/loop.py`** — `AgentLoop` runs an `asyncio` event loop, draining `inbound` with a 1-second timeout. The processing pipeline (`_process_message`, `_run_agent_loop`) is a work in progress.

- **`agent/runner.py`** — `AgentRunner` builds LLM request kwargs and calls `provider.chat_with_retry()` with a 10-second hard timeout.

- **`providers/base.py`** — `LLMProvider` ABC with full retry logic (standard 3-attempt backoff + persistent mode), transient-error detection (status codes, text markers), Retry-After header parsing, and image-stripping fallback. `chat_with_retry` / `chat_stream_with_retry` are the primary call paths.

- **`providers/anthropic.py`** — Converts OpenAI-style message dicts to Anthropic Messages API format, handles prompt caching (`cache_control`), extended thinking (`reasoning_effort`), tool-call format, and streaming via the native Anthropic SDK.

- **`config/schema.py`** — Pydantic `Config` root model. `Config._match_provider()` auto-selects a provider from `providers.*` by matching model name keywords against the provider registry. Supports camelCase ↔ snake_case keys via `alias_generator=to_camel`.

- **`config/loader.py`** — Load/save `Config` as JSON. Default path: `~/.mybot/config.json`.

## Provider wiring

`AgentLoop` currently accepts `provider` as a string name and passes it to `AgentRunner`, but `AgentRunner.provider` is used as an object (calls `provider.chat_with_retry`). The `Config._match_provider()` / `get_provider()` methods on the config object are the intended way to resolve a `ProviderConfig` and instantiate an `LLMProvider` subclass — this wiring is not yet complete in the agent loop.

import asyncio
import sys

import typer

app = typer.Typer()

phoenix_app = typer.Typer(help="Manage the Phoenix tracing server.")
app.add_typer(phoenix_app, name="phoenix")

from rich.console import Console

console = Console()

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.patch_stdout import patch_stdout

from mybot import __logo__
from mybot.cli.stream import StreamRenderer, ThinkingSpinner

_PROMPT_SESSION: PromptSession | None = None


@phoenix_app.command("start")
def phoenix_start():
    """Start the Phoenix Docker container."""
    import subprocess

    from mybot.config.loader import get_config_path, load_config

    cfg = load_config(get_config_path()).phoenix

    running = subprocess.run(
        ["docker", "ps", "-q", "-f", f"name=^{cfg.container_name}$"],
        capture_output=True,
        text=True,
    )
    if running.stdout.strip():
        console.print(
            f"[yellow]Phoenix already running[/yellow] → http://{cfg.host}:{cfg.port}"
        )
        return

    console.print(f"Pulling / starting [bold]{cfg.image}[/bold] …")
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            cfg.container_name,
            "-p",
            f"{cfg.port}:{cfg.port}",
            "-p",
            "4317:4317",
            cfg.image,
        ],
        check=True,
    )
    console.print(f"[green]✓ Phoenix started[/green] → http://{cfg.host}:{cfg.port}")
    console.print(
        "  Set [cyan]phoenix.enabled = true[/cyan] in your config to activate tracing."
    )


@phoenix_app.command("stop")
def phoenix_stop():
    """Stop and remove the Phoenix Docker container."""
    import subprocess

    from mybot.config.loader import get_config_path, load_config

    cfg = load_config(get_config_path()).phoenix

    try:
        subprocess.run(["docker", "stop", cfg.container_name], check=True)
        subprocess.run(["docker", "rm", cfg.container_name], check=True)
        console.print(f"[green]✓ Phoenix stopped[/green]")
    except subprocess.CalledProcessError:
        console.print(
            f"[red]Could not stop '{cfg.container_name}' — is it running?[/red]"
        )
        raise typer.Exit(1)


@app.command()
def onboard(
    workdir: str | None = typer.Option(None, "--workdir", "-w", help="Work Directory")
):
    """Initialize mybot cofigs and workdir"""
    from mybot.config.loader import get_config_path, load_config, save_config
    from mybot.config.schema import Config

    def _apply_workspace_override(loaded: Config) -> Config:
        if workdir:
            loaded.agents.defaults.workspace = workdir
        return loaded

    config_path = get_config_path()

    if not config_path.exists():
        config = _apply_workspace_override(Config())

        save_config(config, config_path)
    else:
        console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
        console.print(
            "  [bold]y[/bold] = overwrite with defaults (existing values will be lost)"
        )
        console.print(
            "  [bold]N[/bold] = refresh config, keeping existing values and adding new fields"
        )
        if typer.confirm("Overwrite?"):
            config = _apply_workspace_override(Config())
            save_config(config, config_path)
            console.print(f"[green]✓[/green] Config reset to defaults at {config_path}")
        else:
            config = _apply_workspace_override(load_config(config_path))
            save_config(config, config_path)
            console.print(
                f"[green]✓[/green] Config refreshed at {config_path} (existing values preserved)"
            )

    agent_cmd = 'mybot ask -m "Hello!"'
    console.print(f"\n{__logo__} mybot is ready!")
    console.print("\nNext steps:")

    console.print(f"  1. Add your API key to [cyan]{config_path}[/cyan]")
    console.print("     Get one at: https://openrouter.ai/keys")
    console.print(f"  2. Chat: [cyan]{agent_cmd}[/cyan]")


@app.command()
def ask(
    message: str = typer.Option(
        None, "--message", "-m", help="Message to send to the llm"
    ),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    logs: bool = typer.Option(
        False, "--logs/--no-logs", help="Show mybot runtime logs during chat"
    ),
):
    """Interact with the agent directly."""
    from loguru import logger

    from mybot.agent.loop import AgentLoop
    from mybot.bus.queue import MessageBus
    from mybot.config.loader import get_config_path, load_config
    from mybot.providers.anthropic import AnthropicProvider

    config_path = get_config_path()
    config = load_config(config_path)

    from mybot.telemetry import setup_tracing

    setup_tracing(config.phoenix)

    bus = MessageBus()

    model = config.agents.defaults.model
    provider_cfg = config.providers.anthropic
    provider = AnthropicProvider(
        api_key=provider_cfg.api_key,
        api_base=provider_cfg.api_base,
        default_model=model,
    )

    if logs:
        logger.enable("mybot")
    else:
        logger.disable("mybot")

    async def _start_mcp():
        from mybot.agent.tools.mcp import MCPManager

        manager = MCPManager(dict(config.mcp.servers))
        if config.mcp.servers:
            await manager.start()
            tools = manager.get_all_tools()
            if tools:
                console.print(
                    f"[dim]MCP: loaded {len(tools)} tool(s) from "
                    f"{len(config.mcp.servers)} server(s)[/dim]"
                )
        else:
            tools = []
        return manager, tools

    def _build_loop(extra_tools):
        return AgentLoop(
            provider=provider,
            model=model,
            bus=bus,
            extra_tools=extra_tools,
            search_config=config.tools.web.search,
            proxy=config.tools.web.proxy,
        )

    if message:
        # Single message mode
        async def run_once():
            from mybot.bus.events import InboundMessage

            mcp_manager, mcp_tools = await _start_mcp()
            agent_loop = _build_loop(mcp_tools)
            loop_task = asyncio.create_task(agent_loop.run())
            await bus.publish_inbound(
                InboundMessage(
                    channel="cli",
                    sender_id="user",
                    chat_id="direct",
                    content=message,
                )
            )
            try:
                msg = await asyncio.wait_for(bus.consume_outbound(), timeout=60.0)
                console.print(msg.content)
            except asyncio.TimeoutError:
                console.print("[red]Timeout waiting for response[/red]")
            finally:
                loop_task.cancel()
                await mcp_manager.stop()

        asyncio.run(run_once())

    else:
        _init_prompt_session()

        console.print(
            f"{__logo__} Interactive mode [bold blue]({config.agents.defaults.model})[/bold blue] — type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit\n"
        )

        if ":" in session_id:
            cli_channel, cli_chat_id = session_id.split(":", 1)
        else:
            cli_channel, cli_chat_id = "cli", session_id

        async def run_interactive():
            mcp_manager, mcp_tools = await _start_mcp()
            agent_loop = _build_loop(mcp_tools)
            bus_task = asyncio.create_task(agent_loop.run())
            turn_done = asyncio.Event()
            turn_done.set()

            turn_response = []
            renderer: StreamRenderer | None = None

            async def _consume_outbound():
                while True:
                    try:
                        msg = await asyncio.wait_for(
                            bus.consume_outbound(), timeout=1.0
                        )
                        if msg.type == "stream":
                            if renderer:
                                await renderer.on_delta(msg.content)
                        elif msg.type == "final":
                            if renderer:
                                await renderer.on_delta(msg.content)
                                await renderer.on_end()
                            turn_response.append((msg.content, msg.metadata))
                            turn_done.set()
                        elif msg.type == "error":
                            if renderer:
                                await renderer.on_end()
                            console.print(f"[red]Error:[/red] {msg.content}")
                            turn_done.set()
                    except asyncio.TimeoutError:
                        continue
                    except asyncio.CancelledError:
                        break

            outbound_task = asyncio.create_task(_consume_outbound())

            try:
                while True:
                    if renderer:
                        renderer.stop_for_input()
                    user_input = await _read_interactive_input_async()
                    command = user_input.strip()
                    if not command:
                        continue

                    turn_done.clear()
                    turn_response.clear()
                    markdown = True
                    renderer = StreamRenderer(render_markdown=markdown)
                    from mybot.bus.events import InboundMessage

                    await bus.publish_inbound(
                        InboundMessage(
                            channel=cli_channel,
                            sender_id="user",
                            chat_id=cli_chat_id,
                            content=user_input,
                            metadata={"_wants_stream": True},
                        )
                    )

                    await turn_done.wait()
            finally:
                outbound_task.cancel()
                bus_task.cancel()
                await mcp_manager.stop()

        asyncio.run(run_interactive())


from contextlib import nullcontext

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory


def _print_cli_progress_line(text: str, thinking: ThinkingSpinner | None) -> None:
    """Print a CLI progress line, pausing the spinner if needed."""
    if not text.strip():
        return
    with thinking.pause() if thinking else nullcontext():
        console.print(f"  [dim]↳ {text}[/dim]")


class SafeFileHistory(FileHistory):
    """FileHistory subclass that sanitizes surrogate characters on write.

    On Windows, special Unicode input (emoji, mixed-script) can produce
    surrogate characters that crash prompt_toolkit's file write.
    """

    def store_string(self, string: str) -> None:
        safe = string.encode("utf-8", errors="surrogateescape").decode(
            "utf-8", errors="replace"
        )
        super().store_string(safe)


def _init_prompt_session() -> None:
    """Create the prompt_toolkit session with persistent file history."""
    global _PROMPT_SESSION, _SAVED_TERM_ATTRS

    # Save terminal state so we can restore it on exit
    try:
        import termios

        _SAVED_TERM_ATTRS = termios.tcgetattr(sys.stdin.fileno())
    except Exception:
        pass

    from mybot.config.paths import get_cli_history_path

    history_file = get_cli_history_path()
    history_file.parent.mkdir(parents=True, exist_ok=True)

    _PROMPT_SESSION = PromptSession(
        history=SafeFileHistory(str(history_file)),
        enable_open_in_editor=False,
        multiline=False,  # Enter submits (single line mode)
    )


async def _read_interactive_input_async() -> str:
    """Read user input using prompt_toolkit (handles paste, history, display).

    prompt_toolkit natively handles:
    - Multiline paste (bracketed paste mode)
    - History navigation (up/down arrows)
    - Clean display (no ghost characters or artifacts)
    """
    if _PROMPT_SESSION is None:
        raise RuntimeError("Call _init_prompt_session() first")
    try:
        with patch_stdout():
            return await _PROMPT_SESSION.prompt_async(
                HTML("<b fg='ansiblue'>You:</b> "),
            )
    except EOFError as exc:
        raise KeyboardInterrupt from exc

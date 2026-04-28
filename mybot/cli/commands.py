import asyncio
import sys

import typer

app = typer.Typer()

from typing import Any

from rich.console import Console

console = Console()

from mybot import __logo__, __version__
from mybot.cli.stream import ThinkingSpinner, StreamRenderer
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.formatted_text import ANSI, HTML


from prompt_toolkit import PromptSession, print_formatted_text

_PROMPT_SESSION: PromptSession | None = None


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

    config_path = get_config_path()
    config = load_config(config_path)
    bus = MessageBus()

    # Hardcoding for now
    provider = "openai"
    model = "gpt5-nano"

    if logs:
        logger.enable("mybot")
    else:
        logger.disable("mybot")

    agent_loop = AgentLoop(provider=provider, model=model, bus=bus)

    # Shared reference for progress callbacks
    _thinking: ThinkingSpinner | None = None

    async def _cli_progress(
        content: str, *, tool_hint: bool = False, **_kwargs: Any
    ) -> None:
        ch = agent_loop.channels_config
        if ch and tool_hint and not ch.send_tool_hints:
            return
        if ch and not tool_hint and not ch.send_progress:
            return
        _print_cli_progress_line(content, _thinking)

    if message:
        # Single message mode — direct call, no bus needed
        async def run_once():
            pass

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
            bus_task = asyncio.create_task(agent_loop.run())
            turn_done = asyncio.Event()
            turn_done.set()

            turn_response = []
            renderer: StreamRenderer | None = None

            async def _consume_outbound():
                
                while True:
                    try:
                        msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                        # Example handling — depends on your message schema
                        if msg.type == "stream":
                            if renderer:
                                renderer.add_chunk(msg.content)

                        elif msg.type == "final":
                            turn_response.append((msg.content, msg.metadata))
                            turn_done.set()

                        elif msg.type == "error":
                            print("Error:", msg.content)
                            turn_done.set()
                            
                    except asyncio.TimeoutError:
                        continue
                    except asyncio.CancelledError:
                        break


            outbound_task = asyncio.create_task(_consume_outbound())


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

                await bus.publish_inbound(InboundMessage(
                    channel=cli_channel,
                    sender_id="user",
                    chat_id=cli_chat_id,
                    content=user_input,
                    metadata={"_wants_stream": True},
                ))

                await turn_done.wait()
                print("GKKKK")

                if turn_response:
                    content, meta = turn_response[0]
                    print(content)
                else:
                    print("WAIT")




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

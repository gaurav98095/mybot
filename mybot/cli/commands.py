import typer

app = typer.Typer()

from rich.console import Console

console = Console()

from mybot import __logo__, __version__


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
def gk():
    print("Hello GK")

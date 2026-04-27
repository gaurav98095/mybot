import typer

app = typer.Typer()

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
        config = load_config(config_path)

    print(config)


    



@app.command()
def gk():
    print("Hello GK")
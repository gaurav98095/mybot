from pathlib import Path


def get_cli_history_path() -> Path:
    """Return the shared CLI history file path."""
    return Path.home() / ".mybot" / "history" / "cli_history"

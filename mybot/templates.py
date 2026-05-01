"""Prompt template loader.

All natural-language prompts live in templates/<usecase>/<name>.md at the
project root. Use ``load("usecase", "name")`` to read them. The result is
cached after the first read so there is no per-call I/O overhead.

Override the base directory with the ``MYBOT_TEMPLATES_DIR`` env var to
swap in a custom prompt set without touching the package code.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def _default_templates_dir() -> Path:
    """Locate the project root by walking up until pyproject.toml is found."""
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate / "templates"
    return here.parent.parent / "templates"


def _templates_dir() -> Path:
    override = os.environ.get("MYBOT_TEMPLATES_DIR", "").strip()
    return Path(override) if override else _default_templates_dir()


@lru_cache(maxsize=None)
def load(usecase: str, name: str) -> str:
    """Return the content of ``templates/<usecase>/<name>.md``, stripped.

    Results are cached for the lifetime of the process — restart to pick up
    edits during development, or call ``load.cache_clear()`` in tests.

    Raises ``FileNotFoundError`` with a helpful message if the file is absent.
    """
    path = _templates_dir() / usecase / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt template not found: {path}\n"
            f"Create templates/{usecase}/{name}.md or set MYBOT_TEMPLATES_DIR."
        )
    return path.read_text(encoding="utf-8").strip()

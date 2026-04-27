"""Streaming renderer for CLI output.

Uses Rich Live with auto_refresh=False for stable, flicker-free
markdown rendering during streaming. Ellipsis mode handles overflow.
"""

from __future__ import annotations

import sys
import time

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text

from mybot import __logo__


def _make_console() -> Console:
    """Create a Console that emits plain text when stdout is not a TTY.

    Rich's spinner, Live render, and cursor-visibility escape codes all
    key off ``Console.is_terminal``. Forcing ``force_terminal=True`` overrode
    the ``isatty()`` check and caused control sequences (``\\x1b[?25l``,
    braille spinner frames) to pollute programmatic consumers such as
    ``docker exec -i`` or pipes, even with ``NO_COLOR`` or ``TERM=dumb``.
    Deferring to ``isatty()`` keeps Rich output in interactive terminals
    and plain text everywhere else (#3265).
    """
    return Console(file=sys.stdout, force_terminal=sys.stdout.isatty())



class ThinkingSpinner:
    """Spinner that shows 'mybot is thinking...' with pause support."""

    def __init__(self, console: Console | None = None):
        c = console or _make_console()
        self._spinner = c.status("[dim]mybot is thinking...[/dim]", spinner="dots")
        self._active = False

    def __enter__(self):
        self._spinner.start()
        self._active = True
        return self

    def __exit__(self, *exc):
        self._active = False
        self._spinner.stop()
        return False

    def pause(self):
        """Context manager: temporarily stop spinner for clean output."""
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            if self._spinner and self._active:
                self._spinner.stop()
            try:
                yield
            finally:
                if self._spinner and self._active:
                    self._spinner.start()

        return _ctx()
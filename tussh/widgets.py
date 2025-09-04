from __future__ import annotations

from textual.widgets import ListItem, Label
from rich.text import Text


class HostItem(ListItem):
    """List row that always carries its alias explicitly.

    Optionally shows a different display label (e.g., with markers) while keeping
    the underlying alias intact for logic.
    """

    def __init__(self, alias: str, display: str | None = None) -> None:
        # Render any markup as styled text chips
        renderable = Text.from_markup(display or alias)
        super().__init__(Label(renderable))
        self.alias = alias

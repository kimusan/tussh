from __future__ import annotations

from textual.widgets import ListItem, Label


class HostItem(ListItem):
    """List row that always carries its alias explicitly."""

    def __init__(self, alias: str) -> None:
        super().__init__(Label(alias))
        self.alias = alias


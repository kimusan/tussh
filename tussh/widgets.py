from __future__ import annotations

from textual.containers import Horizontal
from textual.widgets import ListItem, Label, Static
from rich.text import Text


class HostItem(ListItem):
    """List row which renders markers, alias, and tag chips in aligned columns.

    Keeps `alias` as a plain attribute for selection/logic regardless of styling.
    """

    def __init__(self, alias: str, *, markers: str = "", chips: str = "") -> None:
        markers_text = Text.from_markup(markers) if markers else Text("")
        alias_text = Text(alias)
        chips_text = Text.from_markup(chips) if chips else Text("")

        row = Horizontal(
            Static(markers_text, classes="hi-markers"),
            Static(alias_text, classes="hi-alias"),
            Static(chips_text, classes="hi-chips"),
            classes="hi-row",
        )
        super().__init__(row)
        self.alias = alias

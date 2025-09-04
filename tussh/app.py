from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Dict, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Header,
    Footer,
    Input,
    Static,
    Button,
    DataTable,
    ListView,
    ListItem,
    Label,
)

from .config_io import (
    ConfigIndex,
    read_index,
    hosts_list,
    effective_config,
    default_ssh_config_path,
    add_or_update_host,
    delete_host,
    COMMON_FIELDS_ORDER,
)
from .modals import ConfirmModal, OptionsModal, AddEditHostModal
from .settings import UserSettings
from .widgets import HostItem


# --------------------- Main App ----------------------------------------------


class TusshApp(App):
    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("enter", "connect", "Connect"),
        Binding("a", "add", "Add"),
        Binding("e", "edit", "Edit"),
        Binding("d", "delete", "Delete"),
        Binding("r", "raw_edit", "Raw Edit"),
        Binding("o", "options", "Options"),
        Binding("escape", "quit", "Quit"),
        Binding("q", "quit", show=False),
        Binding("/", "focus_filter", "Filter"),
    ]

    _idx: ConfigIndex | None = None
    _settings: UserSettings
    selected_alias: reactive[str | None] = reactive(None)

    def __init__(self) -> None:
        super().__init__()
        self._settings = UserSettings.load()

    def _alias_from_item(self, item: ListItem) -> str:
        # Preferred: our subclassed item has .alias
        alias = getattr(item, "alias", None)
        if alias:
            return alias
        # Fallbacks for unexpected cases:
        # a) Try to find a Label child if present
        it = item.query(Label)
        for label in it:
            r = getattr(label, "renderable", None)
            return r.plain if r is not None else str(label.render())
        # b) Last resort: string of the item (better than crashing)
        return str(item)

    # ---- Compose UI

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="host-list"):
                yield Input(
                    placeholder="Filter hosts (type / to focus)...", id="filter"
                )
                yield ListView(id="list")
            with Vertical(id="details"):
                yield Label("Details", id="details-title")
                yield DataTable(id="table")
                yield Static("", id="cmdline")
                yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        cfg_path = (
            Path(self._settings.ssh_config_path)
            if self._settings.ssh_config_path
            else default_ssh_config_path()
        )
        self.reload_index(cfg_path)
        self.query_one("#filter", Input).blur()
        # Ensure first host is visibly selected and list has focus
        self.query_one("#list", ListView).focus()
        # Make options table non-focusable / non-selectable
        table = self.query_one("#table", DataTable)
        table.can_focus = False

    # ---- Data loading

    def reload_index(self, path: Path) -> None:
        self._idx = read_index(path)
        lst = self.query_one("#list", ListView)
        lst.clear()

        all_hosts = hosts_list(self._idx)
        all_hosts.sort(key=lambda a: (-self._settings.usage.get(a, 0), a.casefold()))
        for host in all_hosts:
            lst.append(HostItem(host))
        if lst.children:
            lst.index = 0
            self.selected_alias = self._alias_from_item(lst.children[0])
        self.update_details()

    # ---- Helpers

    def _current_alias(self) -> Optional[str]:
        lst = self.query_one("#list", ListView)
        if not lst.children or lst.index is None:
            return None
        return self._alias_from_item(lst.children[lst.index])

    def _set_status(self, msg: str) -> None:
        self.query_one("#status", Static).update(msg)

    def _update_cmd_preview(self) -> None:
        alias = self._current_alias()
        if not alias:
            self.query_one("#cmdline", Static).update("")
            return
        hov = self._settings.host_overrides.get(alias, {})
        client = (hov.get("client") or self._settings.client or "ssh").lower()
        extra = (hov.get("extra_args") or self._settings.extra_args).strip()
        if client == "mosh":
            args: list[str] = ["mosh"]
            if extra:
                args.append(f"--ssh=ssh {extra}")
            args.append(alias)
        else:
            args = ["ssh"]
            if extra:
                args.extend(shlex.split(extra))
            args.append(alias)
        cmd = shlex.join(args)
        self.query_one("#cmdline", Static).update(f"Command preview: [dim]{cmd}[/dim]")

    def update_details(self) -> None:
        table = self.query_one("#table", DataTable)
        table.clear(columns=True)
        # Fixed width for the key column; value column auto-expands
        table.add_column("Key", width=22)
        table.add_column("Value", key="value")
        alias = self._current_alias()
        if not alias or not self._idx:
            self._update_cmd_preview()
            return
        eff = effective_config(self._idx, alias)
        # Show common fields first, then everything else
        shown = set()
        for k in COMMON_FIELDS_ORDER:
            if k in eff:
                table.add_row(k, eff[k])
                shown.add(k)
        for k, v in sorted(eff.items()):
            if k not in shown:
                table.add_row(k, v)

        self._set_status(f"{alias} · {len(eff)} options")
        self._update_cmd_preview()

    # ---- Events

    def on_list_view_highlighted(self, _: ListView.Highlighted) -> None:
        alias = self._current_alias()
        self.selected_alias = alias
        self.update_details()

    def on_list_view_submitted(self, _: ListView.Submitted) -> None:
        # Hitting Enter on the list should connect to the highlighted host
        self.action_connect()

    def on_list_view_selected(self, _: ListView.Selected) -> None:
        # Some Textual versions emit Selected on Enter
        self.action_connect()

    def action_focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "filter":
            return
        token = event.value.strip().lower()
        lst = self.query_one("#list", ListView)
        lst.clear()
        if not self._idx:
            return
        filtered = [h for h in hosts_list(self._idx) if token in h.lower()]
        filtered.sort(key=lambda a: (-self._settings.usage.get(a, 0), a.casefold()))
        for host in filtered:
            lst.append(HostItem(host))
        if lst.children:
            lst.index = 0
            self.selected_alias = self._alias_from_item(lst.children[0])
        else:
            self.selected_alias = None
        self.update_details()

    # ---- Key actions

    def action_connect(self) -> None:
        alias = self._current_alias()
        if not alias:
            self.bell()
            return
        # Bump usage count before exiting to connect
        self._settings.usage[alias] = self._settings.usage.get(alias, 0) + 1
        self._settings.save()
        # Per-host overrides
        hov = self._settings.host_overrides.get(alias, {})
        client = (hov.get("client") or self._settings.client or "ssh").lower()
        if client == "mosh":
            args = ["mosh"]
            # If extra SSH args provided, pass via --ssh
            extra = (hov.get("extra_args") or self._settings.extra_args).strip()
            if extra:
                # Quote inside to keep as one argument
                args.append(f"--ssh=ssh {extra}")
            args.append(alias)
            # Exit app and return the argv to the caller (cli.py) to exec cleanly
            self.exit(args)
        else:
            args = ["ssh"]
            extra = (hov.get("extra_args") or self._settings.extra_args).strip()
            if extra:
                args.extend(shlex.split(extra))
            args.append(alias)
            # Exit app and return argv; the CLI will exec
            self.exit(args)

    def action_add(self) -> None:
        av = hosts_list(self._idx) if self._idx else []
        self.push_screen(
            AddEditHostModal(
                title="Add host", alias=None, options=None, extras_text="", overrides=None, available_hosts=av
            ),
            self._on_add_edit_result,
        )

    def action_edit(self) -> None:
        alias = self._current_alias()
        if not alias or not self._idx:
            self.bell()
            return
        eff = effective_config(self._idx, alias)

        # Split fields into common vs extras
        opts: Dict[str, str] = {}
        extras_lines: list[str] = []
        for k, v in eff.items():
            if k in COMMON_FIELDS_ORDER or k in {"ProxyCommand"}:
                opts[k] = v
            else:
                extras_lines.append(f"{k} {v}")
        self.push_screen(
            AddEditHostModal(
                title="Edit host",
                alias=alias,
                options=opts,
                extras_text="\n".join(extras_lines),
                overrides=self._settings.host_overrides.get(alias, {}),
                available_hosts=hosts_list(self._idx),
            ),
            self._on_add_edit_result,
        )

    def action_raw_edit(self) -> None:
        alias = self._current_alias()
        if not alias or not self._idx:
            self.bell()
            return
        # Raw edit is accomplished by opening the structured modal with empty opts
        # and moving the full current block content to the raw area.
        eff = effective_config(self._idx, alias)
        # Reconstruct raw as lines of `Key Value` in arbitrary order
        raw_lines = []
        for k, v in eff.items():
            raw_lines.append(f"{k} {v}")
        self.push_screen(
            AddEditHostModal(
                title=f"Raw edit: {alias}",
                alias=alias,
                options={},
                extras_text="\n".join(raw_lines),
                raw_mode=True,
                overrides=self._settings.host_overrides.get(alias, {}),
                available_hosts=hosts_list(self._idx),
            ),
            self._on_add_edit_result,
        )

    def _on_add_edit_result(self, result: Optional[tuple]) -> None:
        if not result or not self._idx:
            return
        if len(result) == 4:
            alias, opts, extras, ov = result  # type: ignore[misc]
        else:
            alias, opts, extras = result  # type: ignore[misc]
            ov = {}
        try:
            self._idx, msg = add_or_update_host(self._idx, alias, opts, extras)
            self._set_status(msg)
            if ov:
                self._settings.host_overrides[alias] = ov
            else:
                self._settings.host_overrides.pop(alias, None)
            self._settings.save()
            self.reload_index(self._idx.primary)
        except RuntimeError as e:
            self._set_status(f"[error] {e}")
            self.bell()

    def action_delete(self) -> None:
        alias = self._current_alias()
        if not alias:
            self.bell()
            return
        self.push_screen(
            ConfirmModal(f"Delete host '{alias}'? This cannot be undone."),
            self._on_delete_confirm,
        )

    def _on_delete_confirm(self, confirmed: bool | None) -> None:
        if not confirmed or not self._idx:
            return
        alias = self._current_alias()
        if not alias:
            return
        try:
            self._idx, msg = delete_host(self._idx, alias)
            self._set_status(msg)
            self.reload_index(self._idx.primary)
        except RuntimeError as e:
            self._set_status(f"[error] {e}")
            self.bell()

    def action_options(self) -> None:
        self.push_screen(OptionsModal(self._settings), self._on_options_saved)

    def _on_options_saved(self, settings: Optional[UserSettings]) -> None:
        if settings is None:
            return
        self._settings = settings
        # Possibly re-read index if config_path changed
        path = (
            Path(self._settings.ssh_config_path)
            if self._settings.ssh_config_path
            else default_ssh_config_path()
        )
        self.reload_index(path)

    def action_quit(self) -> None:
        self.exit()

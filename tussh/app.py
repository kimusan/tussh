from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Dict, Optional
import hashlib

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
    Markdown,
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
    TITLE = "TuSSH"

    BINDINGS = [
        Binding("enter", "connect", "Connect"),
        Binding("a", "add", "Add"),
        Binding("e", "edit", "Edit"),
        Binding("d", "delete", "Delete"),
        Binding("r", "raw_edit", "Raw Edit"),
        Binding("o", "options", "Options"),
        Binding("p", "toggle_pin", "Pin"),
        Binding("f", "toggle_favorite", "Fav"),
        Binding("t", "toggle_tags", "Tags"),
        Binding("?", "toggle_help", "Help"),
        Binding("escape", "quit", "Quit"),
        Binding("q", "quit", show=False),
        Binding("/", "focus_filter", "Filter"),
    ]

    _idx: ConfigIndex | None = None
    _settings: UserSettings
    selected_alias: reactive[str | None] = reactive(None)

    def __init__(self) -> None:
        super().__init__()
        try:
            self.title = "TuSSH"
        except Exception:
            pass
        self._settings = UserSettings.load()
        # Apply saved theme as early as possible
        try:
            if getattr(self._settings, "theme", None):
                self.theme = str(self._settings.theme)
        except Exception:
            pass

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
                yield Static("", id="ro-indicator")
                yield DataTable(id="table")
                yield Markdown("", id="notes")
                yield Static("", id="cmdline")
                yield Static("", id="status")
        yield Footer()
        # Help dock overlay (hidden by default; toggled with '?')
        help_body = Static(self._help_text(), id="help-text")
        yield Vertical(
            help_body,
            Button("Close (press ?)", id="help-close"),
            id="help",
        )

    def on_mount(self) -> None:
        # Subscribe to theme changes from Ctrl-P palette and persist them
        try:
            self.theme_changed_signal.subscribe(self, self.on_theme_changed)  # type: ignore[attr-defined]
        except Exception:
            pass
        # Apply persisted Textual theme (selected via palette)
        if getattr(self._settings, "theme", None):
            try:
                self.theme = str(self._settings.theme)
            except Exception:
                pass
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
        # Ensure help is hidden initially
        self._set_help_visible(False)
        # Set help panel border title
        try:
            hp = self.query_one("#help")
            if hasattr(hp, "border_title"):
                setattr(hp, "border_title", "Help")
            hp.styles.border_title = "Help"
        except Exception:
            pass
        # Apply read-only mode UI/keys
        self._apply_read_only_state()
        # Set notes panel border title
        try:
            md = self.query_one("#notes", Markdown)
            if hasattr(md, "border_title"):
                setattr(md, "border_title", "Notes")
            md.styles.border_title = "Notes"
        except Exception:
            pass

    # ---- Data loading

    def reload_index(self, path: Path) -> None:
        self._idx = read_index(path)
        lst = self.query_one("#list", ListView)
        lst.clear()

        all_hosts = hosts_list(self._idx)
        # Sort: pinned first, then usage desc, then alias
        pin_set = set(self._settings.pinned or [])
        all_hosts.sort(key=lambda a: (-1 if a in pin_set else 0, -self._settings.usage.get(a, 0), a.casefold()))
        for host in all_hosts:
            markers, chips = self._markers_and_chips(host)
            lst.append(HostItem(host, markers=markers, chips=chips))
        if all_hosts:
            lst.index = 0
            self.selected_alias = all_hosts[0]
        self.update_details()

    # ---- Helpers

    def _current_alias(self) -> Optional[str]:
        lst = self.query_one("#list", ListView)
        if not lst.children or lst.index is None:
            return None
        return self._alias_from_item(lst.children[lst.index])

    def _set_status(self, msg: str) -> None:
        self.query_one("#status", Static).update(msg)

    def _apply_read_only_state(self) -> None:
        # Update indicator label and hide/show bindings in footer if possible
        ro = bool(getattr(self._settings, "read_only", False))
        try:
            ind = self.query_one("#ro-indicator", Static)
            if ro:
                ind.update("[b][red]READ-ONLY MODE[/red][/b]")
                ind.display = True
            else:
                ind.update("")
                ind.display = False
        except Exception:
            pass
        # Best-effort: hide add/edit/delete bindings from footer
        try:
            # Textual's bindings collection (internal API may vary)
            binds = getattr(self, "bindings", None)
            if binds is not None:
                for b in getattr(binds, "_bindings", []):
                    if getattr(b, "action", "") in {"add", "edit", "delete"}:
                        b.show = not ro
        except Exception:
            pass

    # ---- Tag rendering helpers

    def _tag_bg(self, tag: str) -> str:
        """Deterministic background color name for a tag."""
        palette = [
            "red",
            "green",
            "blue",
            "magenta",
            "cyan",
            "yellow",
            "orange1",
            "deep_sky_blue1",
            "violet",
            "turquoise2",
        ]
        h = hashlib.sha1(tag.encode("utf-8")).digest()[0]
        return palette[h % len(palette)]

    def _tag_chip(self, tag: str) -> str:
        bg = self._tag_bg(tag.lower())
        # Prefer dark text for readability; only use white on very dark backgrounds
        very_dark = {"red", "blue", "magenta", "violet"}
        fg = "white" if bg in very_dark else "black"
        return f"[{fg} on {bg}]#{tag}[/]"

    def _markers_and_chips(self, host: str) -> tuple[str, str]:
        pin_set = set(self._settings.pinned or [])
        fav_set = set(self._settings.favorites or [])
        markers = ("📌" if host in pin_set else "") + ("★" if host in fav_set else "")
        chips = ""
        if self._settings.show_tags_in_list:
            chips = " ".join(self._tag_chip(t) for t in (self._settings.host_tags.get(host, [])))
        return markers, chips

    # ---- Help dock ----

    def _help_text(self) -> str:
        return (
            "[b]TuSSH — Help[/b]\n\n"
            "[b]Navigation[/b]\n"
            "- Arrow keys / j,k: Move selection\n"
            "- / : Focus filter; type to filter (Esc to exit)\n"
            "- Enter: Connect to selected host\n\n"
            "[b]Actions[/b]\n"
            "- a: Add host\n- e: Edit host\n- d: Delete host\n- r: Raw edit\n- o: Options\n- p: Toggle pin\n- f: Toggle favorite\n- t: Toggle tag chips in list\n- ?: Toggle help\n- Esc/q: Quit\n\n"
            "[b]Tags & Filtering[/b]\n"
            "- Add tags in Add/Edit (comma-separated)\n"
            "- Filter by tag using '#tag' or 'tag:tag'\n"
            "- Pinned hosts sort first; favorites show with a star\n\n"
            "[b]Notes[/b]\n"
            "- Add a short note per host in Add/Edit; shown in details\n\n"
            "[b]Themes[/b]\n"
            "- Press Ctrl-P and pick a theme; TuSSH saves and restores it\n\n"
            "[b]Connecting[/b]\n"
            "- TUI suspends while SSH/Mosh runs; resumes after disconnect\n"
            "- Command preview shows the effective argv\n"
        )

    def _set_help_visible(self, visible: bool) -> None:
        help_panel = self.query_one("#help")
        if visible:
            help_panel.add_class("show")
        else:
            help_panel.remove_class("show")

    def action_toggle_help(self) -> None:
        help_panel = self.query_one("#help")
        if "show" in help_panel.classes:
            self._set_help_visible(False)
        else:
            # Refresh content (in case bindings/features changed)
            self.query_one("#help-text", Static).update(self._help_text())
            self._set_help_visible(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "help-close":
            self._set_help_visible(False)

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
            try:
                notes_md = self.query_one("#notes", Markdown)
                notes_md.update("")
                notes_md.display = False
            except Exception:
                pass
            return
        # Update notes markdown block below the table
        note = self._settings.host_notes.get(alias, "").strip()
        try:
            notes_md = self.query_one("#notes", Markdown)
            if note:
                notes_md.update(note)
                notes_md.display = True
            else:
                notes_md.update("")
                notes_md.display = False
        except Exception:
            pass
        tags = self._settings.host_tags.get(alias, [])
        if tags:
            table.add_row("Tags", ", ".join(tags))
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
        # Mouse single-click selects only; do not connect here.
        # Enter is handled via key binding; double-click triggers Submitted.
        pass

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
        def match(h: str) -> bool:
            if not token:
                return True
            if token.startswith("#") and len(token) > 1:
                tag = token[1:]
                tags = [t.lower() for t in self._settings.host_tags.get(h, [])]
                return tag in tags
            if token.startswith("tag:") and len(token) > 4:
                tag = token[4:]
                tags = [t.lower() for t in self._settings.host_tags.get(h, [])]
                return tag in tags
            return token in h.lower()

        filtered = [h for h in hosts_list(self._idx) if match(h)]
        pin_set = set(self._settings.pinned or [])
        filtered.sort(key=lambda a: (-1 if a in pin_set else 0, -self._settings.usage.get(a, 0), a.casefold()))
        for host in filtered:
            markers, chips = self._markers_and_chips(host)
            lst.append(HostItem(host, markers=markers, chips=chips))
        if filtered:
            lst.index = 0
            self.selected_alias = filtered[0]
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
        else:
            args = ["ssh"]
            extra = (hov.get("extra_args") or self._settings.extra_args).strip()
            if extra:
                args.extend(shlex.split(extra))
            args.append(alias)

        # Prefer running the process while suspending Textual, so the app
        # stays alive and resumes when the user disconnects.
        suspend_cm = getattr(self, "suspend", None)
        if suspend_cm is None:
            # Fallback to previous behavior if Textual doesn't support suspend
            self.exit(args)
            return

        self._set_status(f"Connecting to {alias} …")
        rc = 0
        try:
            with suspend_cm():  # type: ignore[misc]
                try:
                    # Clear terminal and print a helpful line that remains visible
                    os.system("clear")
                except Exception:
                    pass
                try:
                    print(f"Connecting to {alias} …")
                except Exception:
                    pass
                try:
                    rc = subprocess.call(args)
                except FileNotFoundError:
                    print(f"Error: '{args[0]}' not found on PATH.")
                    rc = 127
        except Exception:
            # If suspension failed for any reason, fall back to exiting to exec
            self.exit(args)
            return

        # Back in the app after disconnect; reflect result in status
        if rc == 0:
            self._set_status(f"Disconnected from {alias}")
        else:
            self._set_status(f"[error] Connection exited with code {rc}")

    def action_add(self) -> None:
        if getattr(self._settings, "read_only", False):
            self._set_status("Read-only mode: Add is disabled")
            self.bell()
            return
        av = hosts_list(self._idx) if self._idx else []
        self.push_screen(
            AddEditHostModal(
                title="Add host",
                alias=None,
                options=None,
                extras_text="",
                overrides=None,
                available_hosts=av,
                favorite=False,
                pinned=False,
                tags=[],
            ),
            self._on_add_edit_result,
        )

    def action_edit(self) -> None:
        if getattr(self._settings, "read_only", False):
            self._set_status("Read-only mode: Edit is disabled")
            self.bell()
            return
        alias = self._current_alias()
        if not alias or not self._idx:
            self.bell()
            return
        eff = effective_config(self._idx, alias)

        # Split fields into common vs extras
        opts: Dict[str, str] = {}
        extras_lines: list[str] = []
        # Build case-insensitive map to canonical field names
        canon_map: Dict[str, str] = {c.lower(): c for c in COMMON_FIELDS_ORDER}
        canon_map["proxycommand"] = "ProxyCommand"
        for k, v in eff.items():
            ck = canon_map.get(k.lower())
            if ck is not None:
                opts[ck] = v
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
                favorite=alias in (self._settings.favorites or []),
                pinned=alias in (self._settings.pinned or []),
                tags=self._settings.host_tags.get(alias, []),
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
        alias: str
        opts: Dict[str, str]
        extras: str
        ov: Dict[str, str]
        meta: Dict[str, object] = {}
        if len(result) == 5:
            alias, opts, extras, ov, meta = result  # type: ignore[misc]
        elif len(result) == 4:
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
            # Apply metadata (favorite, pinned, tags, notes)
            fav_set = set(self._settings.favorites or [])
            pin_set = set(self._settings.pinned or [])
            if meta:
                if isinstance(meta.get("favorite"), bool):
                    if meta["favorite"]:
                        fav_set.add(alias)
                    else:
                        fav_set.discard(alias)
                if isinstance(meta.get("pinned"), bool):
                    if meta["pinned"]:
                        pin_set.add(alias)
                    else:
                        pin_set.discard(alias)
                if isinstance(meta.get("tags"), list):
                    tags_list = [str(t).strip() for t in meta["tags"] if str(t).strip()]
                    if tags_list:
                        self._settings.host_tags[alias] = tags_list
                    else:
                        self._settings.host_tags.pop(alias, None)
                if isinstance(meta.get("notes"), str):
                    note_val = str(meta["notes"]).strip()
                    if note_val:
                        self._settings.host_notes[alias] = note_val
                    else:
                        self._settings.host_notes.pop(alias, None)
            self._settings.favorites = sorted(fav_set)
            self._settings.pinned = sorted(pin_set)
            self._settings.save()
            current = alias
            self.reload_index(self._idx.primary)
            # Restore selection to the edited/added host if present
            lst = self.query_one("#list", ListView)
            for i, child in enumerate(lst.children):
                if getattr(child, "alias", None) == current:
                    lst.index = i
                    self.selected_alias = current
                    break
        except RuntimeError as e:
            self._set_status(f"[error] {e}")
            self.bell()

    def action_toggle_pin(self) -> None:
        alias = self._current_alias()
        if not alias:
            self.bell()
            return
        pins = set(self._settings.pinned or [])
        if alias in pins:
            pins.discard(alias)
            self._set_status(f"Unpinned {alias}")
        else:
            pins.add(alias)
            self._set_status(f"Pinned {alias}")
        self._settings.pinned = sorted(pins)
        self._settings.save()
        # Reload list preserving selection
        sel = alias
        self.reload_index(self._idx.primary)  # type: ignore[union-attr]
        lst = self.query_one("#list", ListView)
        for i, child in enumerate(lst.children):
            if getattr(child, "alias", None) == sel:
                lst.index = i
                self.selected_alias = sel
                break

    def action_toggle_favorite(self) -> None:
        alias = self._current_alias()
        if not alias:
            self.bell()
            return
        favs = set(self._settings.favorites or [])
        if alias in favs:
            favs.discard(alias)
            self._set_status(f"Removed favorite: {alias}")
        else:
            favs.add(alias)
            self._set_status(f"Favorited {alias}")
        self._settings.favorites = sorted(favs)
        self._settings.save()
        # Reload list preserving selection
        sel = alias
        self.reload_index(self._idx.primary)  # type: ignore[union-attr]
        lst = self.query_one("#list", ListView)
        for i, child in enumerate(lst.children):
            if getattr(child, "alias", None) == sel:
                lst.index = i
                self.selected_alias = sel
                break

    def action_toggle_tags(self) -> None:
        # Toggle visibility of tag chips in the list; persist and refresh
        self._settings.show_tags_in_list = not bool(self._settings.show_tags_in_list)
        self._settings.save()
        state = "shown" if self._settings.show_tags_in_list else "hidden"
        self._set_status(f"List tags {state}")
        sel = self._current_alias()
        self.reload_index(self._idx.primary)  # type: ignore[union-attr]
        if sel:
            lst = self.query_one("#list", ListView)
            for i, child in enumerate(lst.children):
                if getattr(child, "alias", None) == sel:
                    lst.index = i
                    self.selected_alias = sel
                    break

    def action_delete(self) -> None:
        if getattr(self._settings, "read_only", False):
            self._set_status("Read-only mode: Delete is disabled")
            self.bell()
            return
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
        self._apply_read_only_state()
        # Possibly re-read index if config_path changed
        path = (
            Path(self._settings.ssh_config_path)
            if self._settings.ssh_config_path
            else default_ssh_config_path()
        )
        self.reload_index(path)

    def action_quit(self) -> None:
        self.exit()

    # ---- Theme persistence (palette-driven)
    def on_theme_changed(self, theme) -> None:  # type: ignore[override]
        # Persist theme chosen via Ctrl-P palette (payload may vary by Textual version)
        try:
            name: Optional[str] = None
            # Direct string
            if isinstance(theme, str):
                name = theme
            else:
                # Theme object with .name
                n = getattr(theme, "name", None)
                if isinstance(n, str):
                    name = n
                else:
                    # Message-like payload with .theme which may be object or string
                    t = getattr(theme, "theme", None)
                    if isinstance(t, str):
                        name = t
                    else:
                        tn = getattr(t, "name", None)
                        if isinstance(tn, str):
                            name = tn
            if name:
                self._settings.theme = name
                self._settings.save()
        except Exception:
            pass

    # Fallback for versions where App.theme is reactive and watchable
    def watch_theme(self, theme: str) -> None:  # type: ignore[override]
        try:
            self._settings.theme = str(theme)
            self._settings.save()
        except Exception:
            pass

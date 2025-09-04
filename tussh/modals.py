from __future__ import annotations

import os
from typing import Dict, Optional, List

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Collapsible, Input, Label, Select, Static, TextArea

from .config_io import BOOL_KEYS, COMMON_FIELDS_ORDER, default_ssh_config_path
from .settings import UserSettings


class ConfirmModal(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, message: str, *, title: str = "Confirm") -> None:
        super().__init__()
        self._msg = message
        self._title = title

    def compose(self) -> ComposeResult:
        yield Container(
            Vertical(
                Static(self._msg, id="confirm-text"),
                Horizontal(
                    Button("Cancel", id="cancel"),
                    Button("Confirm", variant="error", id="confirm"),
                    classes="buttons",
                ),
                classes="modal-body",
            ),
            id="modal",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_mount(self) -> None:
        modal = self.query_one("#modal", Container)
        if hasattr(modal, "border_title"):
            setattr(modal, "border_title", self._title)
        modal.styles.border_title = self._title


class OptionsModal(ModalScreen[UserSettings]):
    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, settings: UserSettings) -> None:
        super().__init__()
        self._settings = settings

    def compose(self) -> ComposeResult:
        yield Container(
            Vertical(
                VerticalScroll(
                    Vertical(
                        Label("Connection client (ssh or mosh):"),
                        Select(
                            (
                                ("SSH", "ssh"),
                                ("Mosh", "mosh"),
                            ),
                            value=(self._settings.client or "ssh"),
                            id="client_select",
                        ),
                        Label("Extra SSH arguments (appended to every connection):"),
                        Input(
                            self._settings.extra_args,
                            placeholder="-o ConnectTimeout=5 -o PreferredAuthentications=publickey",
                            id="extra_args",
                        ),
                        Label("SSH config path (optional; defaults to ~/.ssh/config):"),
                        Input(
                            self._settings.ssh_config_path or "",
                            placeholder=str(default_ssh_config_path()),
                            id="config_path",
                        ),
                        classes="modal-body",
                    ),
                    id="opts_scroll",
                ),
                Horizontal(
                    Button("Cancel", id="cancel"),
                    Button("Save", variant="primary", id="save"),
                    classes="buttons",
                ),
            ),
            id="modal",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            extra = self.query_one("#extra_args", Input).value.strip()
            cfgp = self.query_one("#config_path", Input).value.strip() or None
            client = self.query_one("#client_select", Select).value or "ssh"
            self._settings.extra_args = extra
            self._settings.ssh_config_path = cfgp
            self._settings.client = client
            self._settings.save()
            self.dismiss(self._settings)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_mount(self) -> None:
        modal = self.query_one("#modal", Container)
        if hasattr(modal, "border_title"):
            setattr(modal, "border_title", "Options")
        modal.styles.border_title = "Options"


class AddEditHostModal(
    ModalScreen[tuple[str, Dict[str, str], str, Dict[str, str]]
                | tuple[str, Dict[str, str], str, Dict[str, str], Dict[str, object]]
                | None]
):
    """Collects fields for Add or Edit. Returns (alias, options, extras_text)."""

    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(
        self,
        *,
        title: str,
        alias: str | None,
        options: Dict[str, str] | None,
        extras_text: str,
        raw_mode: bool = False,
        overrides: Dict[str, str] | None = None,
        available_hosts: Optional[List[str]] = None,
        favorite: bool = False,
        pinned: bool = False,
        tags: Optional[List[str]] = None,
    ) -> None:
        super().__init__()
        self._title = title
        self._alias = alias or ""
        self._opts = options or {}
        self._extras = extras_text
        self._raw = raw_mode
        self._ov = overrides or {}
        self._available_hosts = available_hosts or []
        self._favorite = bool(favorite)
        self._pinned = bool(pinned)
        self._tags = list(tags or [])

    def compose(self) -> ComposeResult:
        def row(label: str, widget) -> Horizontal:
            return Horizontal(
                Label(label, classes="form-label"),
                widget,
                classes="form-row",
            )

        def field_row(label: str, key: str, placeholder: str = "") -> Horizontal:
            val = self._opts.get(key, "")
            inp = Input(val, placeholder=placeholder, id=f"f_{key}")
            return row(label, inp)

        def bool_row(label: str, key: str) -> Horizontal:
            val = self._opts.get(key, "")
            inp = Input(val, placeholder="no", id=f"f_{key}")
            return row(f"{label} (yes/no)", inp)

        self._error = Label("", id="form_error")

        if self._raw:
            # Raw mode: only a big text area editor
            editor = TextArea(self._extras, id="extras", language=None)
            form_body = Vertical(
                editor,
                Label("Per-host overrides (optional)", classes="form-section"),
                row(
                    "Client (ssh/mosh)",
                    Select(
                        (("Default", ""), ("SSH", "ssh"), ("Mosh", "mosh")),
                        id="ov_client",
                        value=self._ov.get("client", ""),
                    ),
                ),
                row(
                    "Extra args (override)",
                    Input(
                        self._ov.get("extra_args", ""),
                        placeholder="e.g. -o ConnectTimeout=3",
                        id="ov_extra",
                    ),
                ),
                Label("Bookmarks & Tags", classes="form-section"),
                row(
                    "Favorite",
                    Select((("Yes", "yes"), ("No", "no")), id="fav_toggle", value=("yes" if self._favorite else "no")),
                ),
                row(
                    "Pinned",
                    Select((("Yes", "yes"), ("No", "no")), id="pin_toggle", value=("yes" if self._pinned else "no")),
                ),
                row(
                    "Tags (comma-separated)",
                    Input(", ".join(self._tags), placeholder="prod, db", id="tags_input"),
                ),
                id="host-form-rows",
                classes="modal-body",
            )
            form = Vertical(
                VerticalScroll(form_body, id="rows_scroll"),
                self._error,
                Horizontal(
                    Button("Cancel", id="cancel"),
                    Button("Save", id="save", variant="primary"),
                    classes="buttons",
                ),
            )
        else:
            rows: list[Horizontal | Static] = []
            if not self._alias:
                rows.append(field_row("Alias (Host)", "Alias", "e.g. prod-db-1"))
            else:
                rows.append(
                    Horizontal(
                        Label("Alias", classes="form-label"),
                        Static(f"Editing: [b]{self._alias}[/b]"),
                        classes="form-row",
                    )
                )

            # initialize builder chain from existing ProxyJump
            self._jb_chain: List[str] = []
            pj_init = (self._opts.get("ProxyJump", "") or "").strip()
            if pj_init:
                self._jb_chain = [p.strip() for p in pj_init.split(",") if p.strip()]

            fields = [
                ("HostName", "HostName", "e.g. 10.0.0.10 or example.com"),
                ("User", "User", "e.g. ubuntu"),
                ("Port", "Port", "22"),
                ("IdentityFile", "IdentityFile", "~/.ssh/id_ed25519"),
                ("ProxyJump", "ProxyJump", "bastion"),
                ("ProxyCommand", "ProxyCommand", "ssh -W %h:%p bastion"),
                ("LocalForward", "LocalForward", "127.0.0.1:9000 127.0.0.1:5432"),
                ("RemoteForward", "RemoteForward", "0.0.0.0:80 127.0.0.1:8080"),
                ("ServerAliveInterval", "ServerAliveInterval", "30"),
                ("ServerAliveCountMax", "ServerAliveCountMax", "3"),
                ("UserKnownHostsFile", "UserKnownHostsFile", "~/.ssh/known_hosts"),
                ("PreferredAuthentications", "PreferredAuthentications", "publickey"),
                ("IdentityAgent", "IdentityAgent", "SSH_AUTH_SOCK"),
            ]
            for lbl, key, ph in fields:
                rows.append(field_row(lbl, key, ph))
                if key == "ProxyJump":
                    # Collapsible builder directly under ProxyJump
                    builder = Collapsible(
                        row(
                            "Select hop",
                            Select(
                                [(h, h) for h in self._available_hosts],
                                id="jb_select",
                                value=self._available_hosts[0]
                                if self._available_hosts
                                else None,
                                classes="jb-select",
                            ),
                        ),
                        row(
                            "Actions",
                            Horizontal(
                                Button("Add", id="jb_add"),
                                Button("Clear", id="jb_clear"),
                                Button("Apply", id="jb_apply"),
                                classes="jb-buttons",
                            ),
                        ),
                        row(
                            "Chain",
                            TextArea(
                                ",".join(self._jb_chain), id="jb_chain", language=None
                            ),
                        ),
                        id="jb_panel",
                        title="ProxyJump Builder",
                    )
                    rows.append(row("", builder))

            for lbl, key in [
                ("ForwardAgent", "ForwardAgent"),
                ("ForwardX11", "ForwardX11"),
                ("StrictHostKeyChecking", "StrictHostKeyChecking"),
                ("Compression", "Compression"),
            ]:
                rows.append(bool_row(lbl, key))

            rows.append(
                row(
                    "Additional options (raw lines; anything not covered above):",
                    TextArea(self._extras, id="extras", language=None),
                )
            )

            # (builder UI now lives directly under ProxyJump row)

            # Per-host overrides section
            rows.append(Label("Per-host overrides (optional)", classes="form-section"))
            rows.append(
                row(
                    "Client (ssh/mosh)",
                    Select(
                        (("Default", ""), ("SSH", "ssh"), ("Mosh", "mosh")),
                        id="ov_client",
                        value=self._ov.get("client", ""),
                    ),
                )
            )
            rows.append(
                row(
                    "Extra args (override)",
                    Input(
                        self._ov.get("extra_args", ""),
                        placeholder="e.g. -o ConnectTimeout=3",
                        id="ov_extra",
                    ),
                )
            )

            # Favorites / Pinned / Tags
            rows.append(Label("Bookmarks & Tags", classes="form-section"))
            rows.append(
                row(
                    "Favorite",
                    Select((("Yes", "yes"), ("No", "no")), id="fav_toggle", value=("yes" if self._favorite else "no")),
                )
            )
            rows.append(
                row(
                    "Pinned",
                    Select((("Yes", "yes"), ("No", "no")), id="pin_toggle", value=("yes" if self._pinned else "no")),
                )
            )
            rows.append(
                row(
                    "Tags (comma-separated)",
                    Input(", ".join(self._tags), placeholder="prod, db", id="tags_input"),
                )
            )

            form = Vertical(
                VerticalScroll(
                    *rows,
                    classes="modal-body",
                    id="rows_scroll",
                ),
                self._error,
                Horizontal(
                    Button("Cancel", id="cancel"),
                    Button("Save", id="save", variant="primary"),
                    classes="buttons",
                ),
            )
        yield Container(form, id="modal")

    # --- Live validation to prevent save until valid (structured mode) ---
    def on_mount(self) -> None:
        modal = self.query_one("#modal", Container)
        if hasattr(modal, "border_title"):
            setattr(modal, "border_title", self._title)
        modal.styles.border_title = self._title
        if not self._raw:
            self._update_save_enabled()

    def on_input_changed(self, _: Input.Changed) -> None:
        if not self._raw:
            self._update_save_enabled()

    def _collect_structured(self) -> tuple[str, Dict[str, str]]:
        opts: Dict[str, str] = {}
        alias = self._alias or ""
        for k in COMMON_FIELDS_ORDER + ["ProxyCommand", "Alias"]:
            widget_id = f"#f_{k}" if k != "Alias" else "#f_Alias"
            w = self.query(widget_id)
            if not w:
                continue
            val = w.first().value.strip()  # type: ignore[attr-defined]
            if k == "Alias":
                alias = self._alias or val
                continue
            if val != "":
                opts[k] = val
        for bk in BOOL_KEYS:
            wq = self.query(f"#f_{bk}")
            if not wq:
                continue
            v = wq.first().value.strip()  # type: ignore[attr-defined]
            if v != "":
                opts[bk] = v
        return alias, opts

    def _validate_structured(self, alias: str, opts: Dict[str, str]) -> list[str]:
        errors: list[str] = []
        if not alias:
            errors.append("Alias is required")
        if "Port" in opts:
            try:
                p = int(opts["Port"])
                if not (1 <= p <= 65535):
                    errors.append("Port must be between 1 and 65535")
            except ValueError:
                errors.append("Port must be an integer")
        for key in ("ServerAliveInterval", "ServerAliveCountMax"):
            if key in opts:
                try:
                    int(opts[key])
                except ValueError:
                    errors.append(f"{key} must be an integer")

        def _is_yes_no(v: str) -> bool:
            return v.lower() in {"yes", "no"}

        for key in ("ForwardAgent", "ForwardX11", "Compression"):
            if key in opts and not _is_yes_no(opts[key]):
                errors.append(f"{key} must be 'yes' or 'no'")
        if "StrictHostKeyChecking" in opts:
            if opts["StrictHostKeyChecking"].lower() not in {"yes", "no", "ask"}:
                errors.append("StrictHostKeyChecking must be 'yes', 'no', or 'ask'")
        return errors

    def _update_save_enabled(self) -> None:
        alias, opts = self._collect_structured()
        errors = self._validate_structured(alias, opts)
        if errors:
            self._error.update("\n".join(f"[error]{e}[/error]" for e in errors))
        else:
            self._error.update("")
        save_btn = self.query_one("#save", Button)
        save_btn.disabled = bool(errors)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "save":
            # Handle jump builder controls
            if event.button.id in {"jb_add", "jb_clear", "jb_apply", "jb_toggle"}:
                if event.button.id == "jb_toggle":
                    panel = self.query_one("#jb_panel")
                    panel.visible = not panel.visible
                    btn = self.query_one("#jb_toggle", Button)
                    btn.label = (
                        "Hide ProxyJump builder"
                        if panel.visible
                        else "Build ProxyJump…"
                    )
                    return
                if event.button.id == "jb_add":
                    sel = self.query_one("#jb_select", Select).value
                    if sel and sel not in getattr(self, "_jb_chain", []):
                        self._jb_chain.append(str(sel))
                        self.query_one("#jb_chain", TextArea).text = ",".join(
                            self._jb_chain
                        )
                elif event.button.id == "jb_clear":
                    self._jb_chain = []
                    self.query_one("#jb_chain", TextArea).text = ""
                elif event.button.id == "jb_apply":
                    if getattr(self, "_jb_chain", []):
                        pj = ",".join(self._jb_chain)
                        self.query_one("#f_ProxyJump", Input).value = pj
                return
            # Cancel
            self.dismiss(None)
            return

        opts: Dict[str, str] = {}
        # Gather fields
        if not self._raw:
            # Auto-apply built chain to field before collecting
            if hasattr(self, "_jb_chain") and self._jb_chain:
                self.query_one("#f_ProxyJump", Input).value = ",".join(self._jb_chain)
            for k in COMMON_FIELDS_ORDER + ["ProxyCommand", "Alias"]:
                widget_id = f"#f_{k}" if k != "Alias" else "#f_Alias"
                w = self.query(widget_id)
                if not w:
                    continue
                val = w.first().value.strip()  # type: ignore[attr-defined]
                if k == "Alias":
                    alias = self._alias or val
                    if not alias:
                        self.app.bell()
                        return
                    continue
                if val != "":
                    opts[k] = val

        # normalize boolean-like values
        if not self._raw:
            for bk in BOOL_KEYS:
                wq = self.query_one(f"#f_{bk}", Input)
                v = wq.value.strip()
                if v != "":
                    opts[bk] = v

        extras = self.query_one("#extras", TextArea).text
        if self._raw:
            alias = self._alias
        else:
            alias = self._alias or self.query_one("#f_Alias", Input).value.strip()
            if not alias:
                self.app.bell()
                return

        # --- Validate on save ---
        errors: list[str] = []
        # Port must be int 1..65535 if set
        if not self._raw and "Port" in opts:
            try:
                p = int(opts["Port"])
                if not (1 <= p <= 65535):
                    errors.append("Port must be between 1 and 65535")
            except ValueError:
                errors.append("Port must be an integer")
        # Intervals
        for key in () if self._raw else ("ServerAliveInterval", "ServerAliveCountMax"):
            if key in opts:
                try:
                    int(opts[key])
                except ValueError:
                    errors.append(f"{key} must be an integer")

        # Booleans in yes/no (except StrictHostKeyChecking allows ask)
        def _is_yes_no(v: str) -> bool:
            return v.lower() in {"yes", "no"}

        if not self._raw:
            for key in ("ForwardAgent", "ForwardX11", "Compression"):
                if key in opts and not _is_yes_no(opts[key]):
                    errors.append(f"{key} must be 'yes' or 'no'")
            if "StrictHostKeyChecking" in opts:
                if opts["StrictHostKeyChecking"].lower() not in {"yes", "no", "ask"}:
                    errors.append("StrictHostKeyChecking must be 'yes', 'no', or 'ask'")

        if errors:
            self._error.update("\n".join(f"[error]{e}[/error]" for e in errors))
            self.app.bell()
            return
        # Collect per-host overrides
        ov: Dict[str, str] = {}
        client_v = self.query_one("#ov_client", Select).value or ""
        if client_v:
            ov["client"] = str(client_v)
        extra_v = self.query_one("#ov_extra", Input).value.strip()
        if extra_v:
            ov["extra_args"] = extra_v

        # Collect UI metadata
        def _is_yes(v: str) -> bool:
            return v.strip().lower() in {"yes", "y", "true", "1"}

        fav_v = (self.query_one("#fav_toggle", Select).value or "no") if self.query("#fav_toggle") else "no"
        pin_v = (self.query_one("#pin_toggle", Select).value or "no") if self.query("#pin_toggle") else "no"
        tags_v = self.query_one("#tags_input", Input).value if self.query("#tags_input") else ""
        tags_list = [t.strip() for t in tags_v.split(",") if t.strip()]

        meta: Dict[str, object] = {
            "favorite": _is_yes(fav_v),
            "pinned": _is_yes(pin_v),
            "tags": tags_list,
        }

        self.dismiss((alias, opts, extras, ov, meta))

    def action_cancel(self) -> None:
        self.dismiss(None)

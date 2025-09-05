from __future__ import annotations

import os
from typing import Dict, Optional, List

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Collapsible, Input, Label, Select, Static, TextArea, Log

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
                        Label("Search mode:"),
                        Select(
                            (("Fuzzy", "fuzzy"), ("Exact only", "exact")),
                            value=("exact" if getattr(self._settings, "exact_match_only", False) else "fuzzy"),
                            id="search_mode_select",
                        ),
                        Label("Mode:"),
                        Select(
                            (("Read/Write", "rw"), ("Read-Only", "ro")),
                            value=("ro" if getattr(self._settings, "read_only", False) else "rw"),
                            id="mode_select",
                        ),
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
            mode = self.query_one("#mode_select", Select).value or "rw"
            search_mode = self.query_one("#search_mode_select", Select).value or "fuzzy"
            self._settings.extra_args = extra
            self._settings.ssh_config_path = cfgp
            self._settings.client = client
            self._settings.read_only = (mode == "ro")
            self._settings.exact_match_only = (search_mode == "exact")
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
    ModalScreen[
        tuple[str, Dict[str, str], str, Dict[str, str]]
        | tuple[str, Dict[str, str], str, Dict[str, str], Dict[str, object]]
        | None
    ]
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
        notes: Optional[str] = None,
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
        self._notes = (notes or "").strip()

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
                # Profile (only when adding)
                (
                    row(
                        "Profile",
                        Select(
                            (
                                ("None", ""),
                                ("Fast connect", "fast"),
                                ("Hardened", "hardened"),
                                ("Low bandwidth", "low_bw"),
                                ("Stable NAT / Idle", "keepalive"),
                                ("Multiplexed persistent", "multiplex"),
                                ("Bastion (ProxyJump)", "bastion"),
                                ("Dev tunnels (LocalForward)", "dev_tunnel"),
                                ("Reverse tunnels (RemoteForward)", "reverse_tunnel"),
                                ("Kerberos / GSSAPI", "kerberos"),
                                ("IPv4 only", "ipv4"),
                                ("X11 forwarding", "x11"),
                                ("Mosh client", "mosh"),
                            ),
                            id="profile_select",
                            value="",
                        ),
                    )
                    if not self._alias
                    else Static("")
                ),
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
                row(
                    "Notes",
                    TextArea(self._notes, id="notes_input", language=None),
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
                # Profile selector for new hosts
                rows.append(
                    row(
                        "Profile",
                        Select(
                            (
                                ("None", ""),
                                ("Fast connect", "fast"),
                                ("Hardened", "hardened"),
                                ("Low bandwidth", "low_bw"),
                                ("Stable NAT / Idle", "keepalive"),
                                ("Multiplexed persistent", "multiplex"),
                                ("Bastion (ProxyJump)", "bastion"),
                                ("Dev tunnels (LocalForward)", "dev_tunnel"),
                                ("Reverse tunnels (RemoteForward)", "reverse_tunnel"),
                                ("Kerberos / GSSAPI", "kerberos"),
                                ("IPv4 only", "ipv4"),
                                ("X11 forwarding", "x11"),
                                ("Mosh client", "mosh"),
                            ),
                            id="profile_select",
                            value="",
                        ),
                    )
                )
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
            rows.append(
                row(
                    "Notes",
                    TextArea(self._notes, id="notes_input", language=None),
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

    # --- Profiles -----------------------------------------------------------
    def _apply_profile(self, key: str) -> None:
        # Define simple presets; keys use canonical capitalization
        extras_lines: list[str] = []
        patch: Dict[str, str] = {}
        if key == "fast":
            patch = {
                "ServerAliveInterval": "20",
                "ServerAliveCountMax": "2",
                "Compression": "yes",
            }
            extras_lines = [
                "ControlMaster auto",
                "ControlPersist 60",
                "ControlPath ~/.ssh/cm/%r@%h:%p",
            ]
            # Ensure ControlMaster dir exists
            try:
                os.makedirs(os.path.expanduser("~/.ssh/cm"), exist_ok=True)
            except Exception:
                pass
        elif key == "hardened":
            patch = {
                "StrictHostKeyChecking": "yes",
                "PreferredAuthentications": "publickey",
                "Compression": "no",
                "ServerAliveInterval": "30",
                "ServerAliveCountMax": "3",
            }
            extras_lines = [
                "PasswordAuthentication no",
                "KbdInteractiveAuthentication no",
                "IdentitiesOnly yes",
            ]
        elif key == "low_bw":
            patch = {
                "Compression": "yes",
                "ServerAliveInterval": "30",
                "ServerAliveCountMax": "3",
                "PreferredAuthentications": "publickey",
            }
            extras_lines = [
                "# Advanced (uncomment if needed):",
                "# Ciphers chacha20-poly1305@openssh.com",
                "# MACs hmac-sha2-256,hmac-sha2-512",
            ]
        elif key == "keepalive":
            patch = {
                "ServerAliveInterval": "15",
                "ServerAliveCountMax": "6",
                "Compression": "no",
            }
            extras_lines = [
                "TCPKeepAlive yes",
            ]
        elif key == "multiplex":
            patch = {
                "ConnectTimeout": "5",
            }
            extras_lines = [
                "ControlMaster auto",
                "ControlPersist 300",
                "ControlPath ~/.ssh/cm/%r@%h:%p",
                "# Optional keepalive:",
                "# ServerAliveInterval 20",
                "# ServerAliveCountMax 3",
            ]
            try:
                os.makedirs(os.path.expanduser("~/.ssh/cm"), exist_ok=True)
            except Exception:
                pass
        elif key == "bastion":
            patch = {
                "ProxyJump": "bastion",
                "StrictHostKeyChecking": "yes",
            }
        elif key == "dev_tunnel":
            patch = {
                "LocalForward": "127.0.0.1:5432 127.0.0.1:5432",
                "ServerAliveInterval": "20",
                "ServerAliveCountMax": "3",
            }
            extras_lines = [
                "# Exit if forward can't be set up:",
                "# ExitOnForwardFailure yes",
            ]
        elif key == "reverse_tunnel":
            patch = {
                "RemoteForward": "0.0.0.0:8080 127.0.0.1:8080",
                "ServerAliveInterval": "20",
                "ServerAliveCountMax": "3",
            }
            extras_lines = [
                "GatewayPorts yes",
            ]
        elif key == "kerberos":
            patch = {
                "PreferredAuthentications": "gssapi-with-mic,publickey",
                "StrictHostKeyChecking": "yes",
            }
            extras_lines = [
                "GSSAPIAuthentication yes",
                "GSSAPIDelegateCredentials no",
            ]
        elif key == "ipv4":
            patch = {
                "ConnectTimeout": "5",
            }
            extras_lines = [
                "AddressFamily inet",
            ]
        elif key == "x11":
            patch = {
                "ForwardX11": "yes",
                "Compression": "yes",
            }
            extras_lines = [
                "ForwardX11Trusted yes",
            ]
        elif key == "mosh":
            try:
                sel = self.query_one("#ov_client", Select)
                sel.value = "mosh"
            except Exception:
                pass
            return
        else:
            return

        # Apply to structured fields where present
        for k, v in patch.items():
            wid = f"#f_{k}"
            try:
                w = self.query_one(wid, Input)
                w.value = v
            except Exception:
                # Unknown/missing field goes to extras
                extras_lines.append(f"{k} {v}")

        # Merge extras
        try:
            ed = self.query_one("#extras", TextArea)
            cur = ed.text.strip()
            prof = "\n".join(extras_lines).strip()
            if prof:
                if cur:
                    ed.text = cur + "\n" + prof + "\n"
                else:
                    ed.text = prof + "\n"
        except Exception:
            pass

    def on_select_changed(self, event: Select.Changed) -> None:  # type: ignore[override]
        if event.select.id == "profile_select" and not self._alias:
            key = (event.value or "").strip()
            if key:
                self._apply_profile(str(key))

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
        notes_v = (
            self.query_one("#notes_input", TextArea).text.strip()
            if self.query("#notes_input")
            else ""
        )

        meta: Dict[str, object] = {
            "favorite": _is_yes(fav_v),
            "pinned": _is_yes(pin_v),
            "tags": tags_list,
            "notes": notes_v,
        }

        self.dismiss((alias, opts, extras, ov, meta))

    def action_cancel(self) -> None:
        self.dismiss(None)


class LogModal(ModalScreen[None]):
    """Shows the live SSH stderr log with copy/clear controls."""

    BINDINGS = [
        Binding("escape", "close", show=False),
        Binding("c", "copy", "Copy last command"),
        Binding("x", "clear", "Clear"),
    ]

    def __init__(self, log_path: str) -> None:
        super().__init__()
        self._log_path = log_path
        self._pos = 0
        self._log: Log | None = None

    def compose(self) -> ComposeResult:
        log = Log(id="log_view")
        log.can_focus = True
        self._log = log
        yield Container(
            Vertical(
                Label("SSH stderr log (latest at bottom)"),
                log,
                Horizontal(
                    Button("Copy last command", id="copy"),
                    Button("Clear", id="clear"),
                    Button("Close", id="close"),
                    classes="buttons",
                ),
                classes="modal-body",
            ),
            id="modal",
        )

    def on_mount(self) -> None:
        modal = self.query_one("#modal", Container)
        if hasattr(modal, "border_title"):
            setattr(modal, "border_title", "Logs")
        modal.styles.border_title = "Logs"
        self._pos = 0
        self._load_all()
        # Periodically tail the file
        self.set_interval(0.5, self._tail_once)

    def _load_all(self) -> None:
        try:
            data = open(self._log_path, "r", encoding="utf-8", errors="ignore").read()
        except OSError:
            data = ""
        self._pos = len(data.encode("utf-8"))
        lg = self._log or self.query_one("#log_view", Log)
        lg.clear()
        if data:
            for line in data.splitlines():
                lg.write_line(line)
            lg.scroll_end(animate=False)

    def _tail_once(self) -> None:
        try:
            with open(self._log_path, "rb") as f:
                f.seek(self._pos)
                chunk = f.read()
                if not chunk:
                    return
                self._pos += len(chunk)
                text = chunk.decode("utf-8", errors="ignore")
        except OSError:
            return
        lg = self._log or self.query_one("#log_view", Log)
        for line in text.splitlines():
            lg.write_line(line)
        lg.scroll_end(animate=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "copy":
            self.action_copy()
        elif event.button.id == "clear":
            self.action_clear()
        elif event.button.id == "close":
            self.action_close()

    def action_copy(self) -> None:
        # Copy the last connection command from the log header line
        try:
            data = open(self._log_path, "r", encoding="utf-8", errors="ignore").read().splitlines()
        except OSError:
            return
        header = None
        for line in reversed(data):
            if line.startswith("----- connection:"):
                header = line
                break
        if not header:
            return
        # Expect format: ----- connection: alias=<alias> cmd=<cmd> time=<...> -----
        cmd = None
        parts = header.split()
        for p in parts:
            if p.startswith("cmd="):
                cmd = p[len("cmd=") :]
                break
        if cmd:
            try:
                self.app.copy_to_clipboard(cmd)  # type: ignore[attr-defined]
                self.app.bell()
            except Exception:
                pass

    def action_clear(self) -> None:
        try:
            with open(self._log_path, "w", encoding="utf-8") as f:
                f.write("")
        except OSError:
            pass
        self._pos = 0
        lg = self._log or self.query_one("#log_view", Log)
        lg.clear()

    def action_close(self) -> None:
        self.dismiss(None)

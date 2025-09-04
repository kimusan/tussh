from __future__ import annotations

import json
from dataclasses import dataclass, field
import json as _json
from pathlib import Path
from typing import Optional, Dict, List

from platformdirs import user_config_dir

APP_NAME = "tussh"
ORG = "tussh"
CONFIG_DIR = Path(user_config_dir(APP_NAME, ORG))
USER_SETTINGS_FILE = CONFIG_DIR / "settings.json"


@dataclass
class UserSettings:
    extra_args: str = ""
    ssh_config_path: Optional[str] = None
    client: str = "ssh"  # "ssh" or "mosh"
    # Textual theme name selected via palette (e.g. "monokai")
    theme: Optional[str] = None
    usage: Dict[str, int] = field(default_factory=dict)
    host_overrides: Dict[str, Dict[str, str]] = field(default_factory=dict)
    favorites: List[str] = field(default_factory=list)
    pinned: List[str] = field(default_factory=list)
    host_tags: Dict[str, List[str]] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "UserSettings":
        try:
            text = Path(USER_SETTINGS_FILE).read_text(encoding="utf-8")
        except OSError:
            return cls()
        try:
            data = _json.loads(text)
        except _json.JSONDecodeError:
            return cls()
        usage = data.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}
        usage_int: Dict[str, int] = {}
        for k, v in usage.items():
            try:
                usage_int[str(k)] = int(v)
            except Exception:
                continue
        host_overrides = data.get("host_overrides") or {}
        if not isinstance(host_overrides, dict):
            host_overrides = {}
        # Ensure keys are strings and sub-keys are strings
        ho_clean: Dict[str, Dict[str, str]] = {}
        for alias, od in host_overrides.items():
            if not isinstance(od, dict):
                continue
            ho_clean[str(alias)] = {
                str(k): str(v) for k, v in od.items() if isinstance(k, str)
            }

        theme_v = data.get("theme")
        if not isinstance(theme_v, str) or not theme_v.strip():
            theme_v = None

        # Clean favorites / pinned lists
        def _clean_list(obj) -> List[str]:
            if not isinstance(obj, list):
                return []
            out: List[str] = []
            for v in obj:
                try:
                    s = str(v).strip()
                    if s:
                        out.append(s)
                except Exception:
                    continue
            return out

        favorites_v = _clean_list(data.get("favorites", []))
        pinned_v = _clean_list(data.get("pinned", []))

        # Clean host_tags mapping -> list[str]
        host_tags_v_raw = data.get("host_tags") or {}
        ht_clean: Dict[str, List[str]] = {}
        if isinstance(host_tags_v_raw, dict):
            for k, v in host_tags_v_raw.items():
                key = str(k)
                vals = _clean_list(v)
                ht_clean[key] = vals

        return cls(
            extra_args=data.get("extra_args", ""),
            ssh_config_path=data.get("ssh_config_path"),
            client=data.get("client", "ssh"),
            theme=theme_v,
            usage=usage_int,
            host_overrides=ho_clean,
            favorites=favorites_v,
            pinned=pinned_v,
            host_tags=ht_clean,
        )

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        Path(USER_SETTINGS_FILE).write_text(
            json.dumps(self.__dict__, indent=2), encoding="utf-8"
        )

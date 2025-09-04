from __future__ import annotations

import fnmatch
import io
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple, Iterable

# ---- Notes on parsing/writing ---------------------------------------------
# - We support:
#   * Include (with glob expansion), relative to file directory.
#   * "first match wins" rule, merging Host blocks in file order to compute
#     final effective config for a given alias.
#   * Multi-name Host blocks (e.g., "Host foo bar"), wildcards are *not*
#     listed in the left pane, but they still contribute inherited options.
# - Writing:
#   * We only write to the primary config (~/.ssh/config or %USERPROFILE%\.ssh\config).
#   * If an alias is defined in an included file, we allow read but block edit/delete,
#     surfacing a clear warning so the user can move it if desired.
#   * We rewrite the specific Host block we touch (or append a new one).
#   * We don’t attempt to preserve comments within that touched block.
# ---------------------------------------------------------------------------

COMMON_FIELDS_ORDER = [
    "HostName",
    "User",
    "Port",
    "IdentityFile",
    "ProxyJump",
    "ProxyCommand",
    "ForwardAgent",
    "ForwardX11",
    "LocalForward",
    "RemoteForward",
    "ServerAliveInterval",
    "ServerAliveCountMax",
    "StrictHostKeyChecking",
    "UserKnownHostsFile",
    "PreferredAuthentications",
    "Compression",
    "IdentityAgent",
]

# Keys we show with booleans in the form:
BOOL_KEYS = {"ForwardAgent", "ForwardX11", "Compression", "StrictHostKeyChecking"}

WS = re.compile(r"\s+")
COMMENT = re.compile(r"^\s*#")
KV = re.compile(r"^\s*([A-Za-z][A-Za-z0-9]+)\s+(.*)$")


@dataclass
class HostBlock:
    file: Path
    start: int
    end: int
    patterns: List[str] = field(default_factory=list)
    options: Dict[str, str] = field(default_factory=dict)


@dataclass
class ConfigIndex:
    primary: Path
    all_files: List[Path]
    blocks: List[HostBlock]


def expand_includes(line_value: str, base_dir: Path) -> List[Path]:
    out = []
    for token in WS.split(line_value.strip()):
        if not token:
            continue
        for p in base_dir.glob(token):
            if p.is_file():
                out.append(p)
    return out


def parse_file(path: Path) -> Tuple[List[HostBlock], List[Path]]:
    blocks: List[HostBlock] = []
    includes: List[Path] = []

    if not path.exists():
        return blocks, includes

    with path.open("r", encoding="utf-8") as f:
        lines = f.readlines()

    cur: HostBlock | None = None
    for i, raw in enumerate(lines):
        line = raw.rstrip("\n")
        if COMMENT.match(line) or not line.strip():
            continue

        m = KV.match(line)
        if not m:
            continue

        key, val = m.group(1), m.group(2).strip()
        if key.lower() == "include":
            includes.extend(expand_includes(val, path.parent))
            continue

        if key.lower() == "host":
            # close previous
            if cur is not None:
                cur.end = i - 1
                blocks.append(cur)
            # start new
            patterns = [t for t in WS.split(val) if t]
            cur = HostBlock(file=path, start=i, end=i, patterns=patterns, options={})
            continue

        if cur is not None:
            cur.options.setdefault(key, val)  # first key wins inside the block
        # (we ignore top-level keys not under "Host", except Include which we handled)

    if cur is not None:
        cur.end = len(lines) - 1
        blocks.append(cur)

    return blocks, includes


def read_index(primary: Path) -> ConfigIndex:
    visited: set[Path] = set()
    queue: List[Path] = [primary]
    all_blocks: List[HostBlock] = []
    all_files: List[Path] = []

    while queue:
        f = queue.pop(0)
        f = f.resolve()
        if f in visited or not f.exists():
            continue
        visited.add(f)
        blocks, incs = parse_file(f)
        all_blocks.extend(blocks)
        all_files.append(f)
        # breadth-first keeps file order stable enough for our purposes
        for inc in incs:
            if inc.exists():
                queue.append(inc)

    # Maintain stable order by the order files were discovered, then line index
    order_map = {p: i for i, p in enumerate(all_files)}
    all_blocks.sort(key=lambda b: (order_map[b.file], b.start))

    return ConfigIndex(primary=primary, all_files=all_files, blocks=all_blocks)


def is_pattern(name: str) -> bool:
    return any(ch in name for ch in "*?!")


def explicit_aliases(block: HostBlock) -> List[str]:
    # Only names with no wildcard chars
    return [
        p for p in block.patterns if not is_pattern(p) and not p.startswith("!")
    ]  # exclude negations


def matching(name: str, patterns: Iterable[str]) -> bool:
    matched = False
    for p in patterns:
        if p.startswith("!"):
            if fnmatch.fnmatchcase(name, p[1:]):
                return False
        else:
            if fnmatch.fnmatchcase(name, p):
                matched = True
    return matched


def effective_config(idx: ConfigIndex, alias: str) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    for block in idx.blocks:
        if matching(alias, block.patterns):
            for k, v in block.options.items():
                merged.setdefault(k, v)  # first-wins
    return merged


def hosts_list(idx: ConfigIndex) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for b in idx.blocks:
        for a in explicit_aliases(b):
            if a not in seen:
                seen.add(a)
                out.append(a)
    out.sort(key=str.casefold)
    return out


# ---- Writing helpers --------------------------------------------------------


def _read_lines(path: Path) -> List[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines(True)  # keep \n


def _write_lines(path: Path, lines: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.writelines(lines)


def _format_block(alias: str, options: Dict[str, str], extras_text: str) -> str:
    buf = io.StringIO()
    buf.write(f"Host {alias}\n")
    # Common fields in a nice order first
    for k in COMMON_FIELDS_ORDER:
        if k in options and options[k] != "":
            buf.write(f"  {k} {options[k]}\n")
    # Then any other keys not covered
    for k, v in options.items():
        if k not in COMMON_FIELDS_ORDER and v != "":
            buf.write(f"  {k} {v}\n")
    # Then raw extras (user supplied)
    if extras_text.strip():
        # Normalize lines and indentation
        for line in extras_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                buf.write(line + "\n")
            else:
                buf.write(f"  {line}\n")
    return buf.getvalue()


@dataclass
class HostLocation:
    file: Path
    start: int
    end: int
    whole_block_names: List[str]  # all names on the 'Host ...' line


def locate_host_block(idx: ConfigIndex, alias: str) -> HostLocation | None:
    for b in idx.blocks:
        names = explicit_aliases(b)
        if alias in names:
            return HostLocation(
                file=b.file, start=b.start, end=b.end, whole_block_names=b.patterns
            )
    return None


def add_or_update_host(
    idx: ConfigIndex, alias: str, options: Dict[str, str], extras_text: str
) -> Tuple[ConfigIndex, str]:
    """
    Returns: (new_index, info_message)
    """
    loc = locate_host_block(idx, alias)
    block_text = _format_block(alias, options, extras_text)

    if loc is None:
        # Append to primary
        lines = _read_lines(idx.primary)
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        if lines and lines[-1].strip():
            lines.append("\n")  # blank separator
        lines.append(block_text if block_text.endswith("\n") else block_text + "\n")
        _write_lines(idx.primary, lines)
        return read_index(idx.primary), f"Added host '{alias}' to {idx.primary}"
    else:
        # Editing only allowed if block resides in primary and the block has *only* this alias
        if loc.file != idx.primary:
            raise RuntimeError(
                f"Host '{alias}' is defined in included file: {loc.file}. "
                f"Edit that file or move the host to {idx.primary}."
            )
        if len([n for n in loc.whole_block_names if not is_pattern(n)]) > 1:
            raise RuntimeError(
                f"Host '{alias}' is in a multi-alias block ({' '.join(loc.whole_block_names)}). "
                f"Editing this block would affect other aliases. Split it first in your config."
            )
        lines = _read_lines(idx.primary)
        new_lines = (
            lines[: loc.start]
            + [block_text if block_text.endswith("\n") else block_text + "\n"]
            + lines[loc.end + 1 :]
        )
        _write_lines(idx.primary, new_lines)
        return read_index(idx.primary), f"Updated host '{alias}' in {idx.primary}"


def delete_host(idx: ConfigIndex, alias: str) -> Tuple[ConfigIndex, str]:
    loc = locate_host_block(idx, alias)
    if loc is None:
        raise RuntimeError(f"Host '{alias}' not found.")
    if loc.file != idx.primary:
        raise RuntimeError(
            f"Host '{alias}' is defined in included file: {loc.file}. Delete it there."
        )
    lines = _read_lines(idx.primary)
    new_lines = lines[: loc.start] + lines[loc.end + 1 :]
    _write_lines(idx.primary, new_lines)
    return read_index(idx.primary), f"Deleted host '{alias}' from {idx.primary}"


def default_ssh_config_path() -> Path:
    # Unix + Windows (OpenSSH on Windows also uses ~/.ssh/config)
    return Path(os.path.expanduser("~")) / ".ssh" / "config"

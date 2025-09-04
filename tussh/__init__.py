from __future__ import annotations

__all__ = ["__version__"]

try:  # Python 3.8+
    from importlib.metadata import PackageNotFoundError, version
except Exception:  # pragma: no cover - fallback for very old Pythons
    from importlib_metadata import PackageNotFoundError, version  # type: ignore

def _detect_version() -> str:
    try:
        return version("tussh")
    except PackageNotFoundError:
        # Fallback: parse pyproject.toml if running from source without install
        try:
            import re
            from pathlib import Path

            text = Path(__file__).resolve().parent.parent.joinpath("pyproject.toml").read_text(encoding="utf-8")
            m = re.search(r"^version\s*=\s*\"([^\"]+)\"", text, flags=re.M)
            if m:
                return m.group(1)
        except Exception:
            pass
        return "0+unknown"

__version__ = _detect_version()

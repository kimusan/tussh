import os
import sys
from typing import Any, List

from .app import TusshApp


def main() -> None:
    result: Any = TusshApp().run()
    # If the app returned an argv list, exec it so the session owns the TTY
    if isinstance(result, list) and result and isinstance(result[0], str):
        argv: List[str] = result
        prog = argv[0]
        # Print a friendly connection line that remains visible during startup
        try:
            target = argv[-1] if len(argv) > 0 else ""
            sys.stdout.write(f"Connecting to {target} …\n")
            sys.stdout.flush()
        except Exception:
            pass
        try:
            os.execvp(prog, argv)
        except FileNotFoundError:
            sys.stderr.write(f"Error: '{prog}' not found on PATH.\n")
            sys.stderr.flush()

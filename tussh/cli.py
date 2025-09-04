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
        try:
            os.execvp(prog, argv)
        except FileNotFoundError:
            sys.stderr.write(f"Error: '{prog}' not found on PATH.\n")
            sys.stderr.flush()

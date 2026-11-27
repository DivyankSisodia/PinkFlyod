"""Native file dialogs, run in a child process so Tk never shares a thread with the web server.

    python -m shorts_studio.media.dialog_proc open_files "Title"
    python -m shorts_studio.media.dialog_proc open_file  "Title"
    python -m shorts_studio.media.dialog_proc open_folder "Title"

Prints a JSON list of chosen paths (empty when cancelled).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

MEDIA_TYPES = [("Video and images", "*.mp4 *.mov *.m4v *.mkv *.webm *.avi *.mts *.m2ts *.wmv *.png *.jpg *.jpeg *.webp"),
               ("All files", "*.*")]


def tcl_environment() -> None:
    """Python 3.13.0 on Windows can't find Tcl/Tk from inside a virtual environment (fixed in 3.13.1).
    Point it at the base installation's copy when the variables aren't set already."""
    base = Path(sys.base_prefix) / "tcl"
    for var, folder in (("TCL_LIBRARY", "tcl8.6"), ("TK_LIBRARY", "tk8.6")):
        lib = base / folder
        if var not in os.environ and (lib / ("init.tcl" if var == "TCL_LIBRARY" else "tk.tcl")).is_file():
            os.environ[var] = str(lib)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "open_files"
    title = sys.argv[2] if len(sys.argv) > 2 else "Choose files"
    tcl_environment()
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.update()
    try:
        if mode == "open_folder":
            chosen = filedialog.askdirectory(parent=root, title=title, mustexist=True)
            paths = [chosen] if chosen else []
        elif mode == "open_file":
            chosen = filedialog.askopenfilename(parent=root, title=title, filetypes=MEDIA_TYPES)
            paths = [chosen] if chosen else []
        else:
            paths = list(filedialog.askopenfilenames(parent=root, title=title, filetypes=MEDIA_TYPES))
    finally:
        root.destroy()
    sys.stdout.write(json.dumps(paths))


if __name__ == "__main__":
    main()

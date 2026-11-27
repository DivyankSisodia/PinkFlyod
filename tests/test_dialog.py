"""The native file dialog's process can start Tk (without showing anything)."""
from __future__ import annotations

import subprocess
import sys

CHECK = ("from shorts_studio.media.dialog_proc import tcl_environment; tcl_environment(); import tkinter; "
         "r = tkinter.Tk(); r.withdraw(); print(r.tk.eval('info patchlevel')); r.destroy()")


def test_tk_initialises_in_this_environment():
    out = subprocess.run([sys.executable, "-c", CHECK], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-500:]
    assert out.stdout.strip().startswith("8.")

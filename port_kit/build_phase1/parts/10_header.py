#!/usr/bin/env python3
"""
cxvr_control_panel_qt.py -- the CXVR headset fleet control panel, rebuilt in
PySide6 (Qt). This is the port of cxvr_control_panel.py (Tkinter); until the
port is finished and has passed a rehearsal with the fleet, the Tkinter file
stays the production tool. Both read and write the same settings in
~/.cxvr_control_panel/, so going back is just a matter of starting the other one.

What is carried over unchanged (and checked by the port kit's integrity test):
  * every embedded script, byte for byte, in EMBEDDED_SCRIPTS;
  * the constants, the process helpers and the terminal backend;
  * all the logic inside ControlPanel below the line that says so -- every
    action, command builder, confirmation and safety check -- character for
    character, apart from three mechanical substitutions (tk.StringVar ->
    StringVar, tk.BooleanVar -> BooleanVar, tk.TclError -> RuntimeError).
What is new: the window, the pages and the small compatibility layer that lets
that logic run on Qt (settings variables, message boxes, Start/Stop switches).

Starting it: double-click it in the file manager, or run it with any Python 3.
If that Python doesn't have PySide6 (the system one usually doesn't), the file
starts itself again with ~/.pyvenv/bin/python, or with $CXVR_QT_PYTHON if set.

For support only:  --screenshot DIR  renders the main pages to PNG files
without starting anything (no watchdogs, no adb), then exits.
"""

import atexit
import functools
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
import queue
import select


def _relaunch_with_venv_python():
    """Double-clicking this file in a file manager starts it with whatever Python
    the desktop picks -- normally the system one, which doesn't have PySide6.
    When that happens, start this same file again with the Python in ~/.pyvenv
    (or $CXVR_QT_PYTHON), which does.

    A venv's bin/python is a symlink to the system Python, so candidates are
    compared by where they live, never by the binary they resolve to. The
    CXVR_RELAUNCHED flag makes sure this re-launches at most once."""
    try:
        import PySide6
    except ImportError:
        PySide6 = None
    if PySide6 is not None:
        os.environ.pop("CXVR_RELAUNCHED", None)   # don't leak the flag to anything started from here
        return
    here = os.path.abspath(__file__)
    current = os.path.abspath(sys.executable)
    if not os.environ.get("CXVR_RELAUNCHED"):
        for candidate in (os.environ.get("CXVR_QT_PYTHON", ""), os.path.expanduser("~/.pyvenv/bin/python")):
            if candidate and os.path.abspath(candidate) != current and os.access(candidate, os.X_OK):
                os.environ["CXVR_RELAUNCHED"] = "1"
                os.execv(candidate, [candidate, here] + sys.argv[1:])
    message = (f"PySide6 isn't available to the Python that started this file:\n{sys.executable}\n\n"
               f"The CXVR control panel (Qt) normally runs with ~/.pyvenv/bin/python. Install PySide6 there with\n"
               f"    ~/.pyvenv/bin/pip install PySide6\n"
               f"or set CXVR_QT_PYTHON to a Python that has it.\n\n"
               f"The Tkinter panel (cxvr_control_panel.py) doesn't need PySide6 and still works.")
    print(message, file=sys.stderr)
    if os.environ.get("DISPLAY") and not os.environ.get("CXVR_NO_DIALOG"):
        try:   # launched from a file manager there's no terminal, so say it in a window too
            import tkinter
            from tkinter import messagebox as tk_messagebox
            root = tkinter.Tk()
            root.withdraw()
            tk_messagebox.showerror("CXVR", message)
            root.destroy()
        except Exception:
            pass
    sys.exit(1)


if __name__ == "__main__":
    _relaunch_with_venv_python()

# PySide6 is imported only here, after the relaunch above has had its chance.
from PySide6 import __version__ as PYSIDE6_VERSION
from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt, QTimer, qVersion
from PySide6.QtGui import QColor, QFont, QPainter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QBoxLayout, QButtonGroup, QCheckBox, QComboBox, QDockWidget, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)
from shiboken6 import isValid as _qt_alive


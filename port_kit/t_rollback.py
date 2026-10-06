#!/usr/bin/env python3
"""Rollback: going back to the Tkinter panel must just work on a config the Qt
panel wrote, and must not throw away the Qt panel's own keys.

  1. Qt panel (venv Python, offscreen): mark two features tested, switch on the
     visual check, put the log pane on the right, close -> config.json.
  2. Tk panel (Python 3.11 with Tkinter, under Xvfb): starts on that config,
     shows the tested state, saves its settings, closes.
  3. Qt panel again: still finds its window layout (the Tk panel kept the keys).

usage: t_rollback.py QT_PANEL TK_PANEL VENV_PY TK_PY
       (run it under xvfb-run so the Tk step has a display)"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
qt_panel, tk_panel, venv_py, tk_py = (os.path.abspath(a) if i < 2 else a for i, a in enumerate(sys.argv[1:5]))
home = tempfile.mkdtemp(prefix="cxvr_rollback_")
env = dict(os.environ, HOME=home, CXVR_TEST_HOME=home)

QT_STEP1 = r'''
import sys, os
sys.path.insert(0, sys.argv[2]); sys.path.insert(0, os.path.join(sys.argv[2], "common"))
import harness_qt
ad = harness_qt.QtPanel(sys.argv[1]); ad.install_stubs(); ad.start()
p = ad.p
from PySide6.QtCore import Qt
p._mark_tested("power.reboot", p.show_menu_power); p._mark_tested("delete_video.delete", p.show_menu_testing)
ad.open("connect"); ad.check("visual_check_var", True)
p.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, p.log_dock); ad.pump(0.1)
p.close(); ad.pump(0.1); print("QT1 OK")
'''
TK_STEP = r'''
import sys, os, json
sys.path.insert(0, sys.argv[2]); sys.path.insert(0, os.path.join(sys.argv[2], "common"))
import harness_tk
ad = harness_tk.TkPanel(sys.argv[1]); ad.install_stubs(); ad.start()
p = ad.p
checks = {
    "tested features respected": sorted(p.tested_features) == ["delete_video.delete", "power.reboot"],
    "visual check restored": p.visual_check_var.get() is True,
    "Delete Video on its main menu": "delete_video" in ad.nav_items()[0],
}
p._save_settings()
cfg = json.load(open(p.CONFIG_FILE if hasattr(p, "CONFIG_FILE") else ad.pm.CONFIG_FILE))
checks["kept window_geometry and dock_state"] = bool(cfg.get("window_geometry")) and bool(cfg.get("dock_state"))
ad.stop()
print("TK " + json.dumps(checks))
'''
QT_STEP2 = r'''
import sys, os
sys.path.insert(0, sys.argv[2]); sys.path.insert(0, os.path.join(sys.argv[2], "common"))
import harness_qt
from PySide6.QtCore import Qt
ad = harness_qt.QtPanel(sys.argv[1]); ad.install_stubs(); ad.start()
p = ad.p
ok = p.dockWidgetArea(p.log_dock) == Qt.DockWidgetArea.RightDockWidgetArea and p.visual_check_var.get() is True
print("QT2 " + ("OK" if ok else "FAIL"))
'''


def run(py, code, panel, extra_env=None):
    script = os.path.join(home, "step.py")
    with open(script, "w") as f:
        f.write(code)
    out = subprocess.run([py, script, panel, HERE], env=dict(env, **(extra_env or {})), capture_output=True,
                         text=True, timeout=120)
    return out.stdout + out.stderr


results = []
out1 = run(venv_py, QT_STEP1, qt_panel)
results.append(("Qt panel wrote its config", "QT1 OK" in out1, out1[-400:]))
cfg = json.load(open(os.path.join(home, ".cxvr_control_panel", "config.json")))
results.append(("config has the Qt-only keys", bool(cfg.get("window_geometry") and cfg.get("dock_state")), cfg.keys()))
out2 = run(tk_py, TK_STEP, tk_panel)
line = next((ln for ln in out2.splitlines() if ln.startswith("TK ")), None)
if line is None:
    results.append(("Tk panel started on the Qt-written config", False, out2[-600:]))
else:
    results.append(("Tk panel started on the Qt-written config", True, ""))
    for name, ok in json.loads(line[3:]).items():
        results.append((f"Tk: {name}", ok, ""))
out3 = run(venv_py, QT_STEP2, qt_panel)
results.append(("Qt panel restored its layout after the Tk panel saved", "QT2 OK" in out3, out3[-400:]))
for name, ok, detail in results:
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -- {detail}"))
print(f"rollback {sum(1 for r in results if r[1])} / {len(results)}")
sys.exit(0 if all(r[1] for r in results) else 1)

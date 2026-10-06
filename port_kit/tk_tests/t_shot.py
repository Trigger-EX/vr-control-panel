import os, sys, faulthandler
faulthandler.dump_traceback_later(60, exit=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["PATH"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakebin") + ":" + os.environ["PATH"]
from harness import load, pump, real_run, wait_for
import tkinter as tk
pm = load(os.environ.get("CXVR_PANEL", "cxvr_control_panel.py"))
W, H = int(sys.argv[1]), int(sys.argv[2])
root = tk.Tk(); p = pm.ControlPanel(root); root.geometry(f"{W}x{H}+0+0"); pump(root, 0.4)
p._terminal_unlocked = True; p._update_terminal_visibility(); pump(root, 0.3)
p._term_refresh_targets()
def type_line(s):
    p.term_entry.delete(0, "end"); p.term_entry.insert(0, s); p._term_on_return()
type_line("ls -1 / | head -3; echo done")
wait_for(root, lambda: "done\n" in p.term_text.get("1.0", "end"), 5)
for m in sys.argv[3:]:
    getattr(p, m)(); pump(root, 0.6)
    real_run(["import", "-window", "root", "-crop", f"{W}x{H}+0+0", f"shot_{W}x{H}_{m}.png"])
p._on_close()

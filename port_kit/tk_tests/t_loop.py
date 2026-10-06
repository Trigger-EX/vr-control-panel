import os, sys, faulthandler, time
faulthandler.dump_traceback_later(30, exit=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["PATH"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakebin") + ":" + os.environ["PATH"]
from harness import load, pump
import tkinter as tk
pm = load(os.environ.get("CXVR_PANEL", "cxvr_control_panel.py"))
W, H = int(sys.argv[1]), int(sys.argv[2])
root = tk.Tk(); p = pm.ControlPanel(root); root.geometry(f"{W}x{H}+0+0"); pump(root, 0.3)
p._terminal_unlocked = True; p._update_terminal_visibility(); pump(root, 0.3)
if p._log_body.winfo_manager(): p._toggle_log_visible()
pump(root, 0.3)
n = [0]; orig = p._update_actions_scroll
def wrapped():
    n[0] += 1; orig()
    if n[0] <= 16:
        c = p._actions_canvas
        print(n[0], "V", int(p._scrollbar_shown["v"]), "H", int(p._scrollbar_shown["h"]),
              "reqh", p.actions_container.winfo_reqheight(), "canvh", c.winfo_height(),
              "reqw", p.actions_container.winfo_reqwidth(), "canvw", c.winfo_width(),
              "rooth", root.winfo_height(), "termh", p.term_section.winfo_height(), flush=True)
    if n[0] == 17: raise SystemExit("looping")
p._update_actions_scroll = wrapped
p.show_menu_volume()
end = time.time() + 2
while time.time() < end: root.update(); time.sleep(0.01)
print("settled after", n[0])

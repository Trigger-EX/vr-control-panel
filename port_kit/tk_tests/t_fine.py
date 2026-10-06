import os, sys, faulthandler, time
faulthandler.dump_traceback_later(170, exit=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["PATH"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakebin") + ":" + os.environ["PATH"]
from harness import load, pump
import tkinter as tk
pm = load(os.environ.get("CXVR_PANEL", "cxvr_control_panel.py")); W = int(sys.argv[1])
root = tk.Tk(); p = pm.ControlPanel(root); root.geometry(f"{W}x640+0+0"); pump(root, 0.3)
p._terminal_unlocked = True; p._update_terminal_visibility(); pump(root, 0.3)
if p._log_body.winfo_manager(): p._toggle_log_visible()
n = [0]; orig = p._update_actions_scroll
def wrapped():
    n[0] += 1; orig()
p._update_actions_scroll = wrapped
bad = 0; total = 0
for m in ("show_menu_volume", "show_menu_sleepwake", "show_menu_sync", "show_menu_screencap", "show_menu_delete_video"):
    getattr(p, m)(); pump(root, 0.3)
    for H in range(640, 820, 2):
        root.geometry(f"{W}x{H}"); n[0] = 0
        end = time.time() + 0.12
        while time.time() < end: root.update(); time.sleep(0.005)
        n[0] = 0
        end = time.time() + 0.1
        while time.time() < end: root.update(); time.sleep(0.005)
        total += 1
        if n[0] > 3 or p.actions_container.winfo_reqwidth() > p._actions_canvas.winfo_width() + 1:
            bad += 1; print("FAIL", W, H, m, n[0], flush=True)
print(f"fine W={W}: {total - bad}/{total} settled", flush=True)
p._on_close()

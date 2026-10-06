import os, sys, faulthandler
faulthandler.dump_traceback_later(float(os.environ.get("FT", "25")), exit=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["PATH"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakebin") + ":" + os.environ["PATH"]
from harness import load, pump, real_run
import tkinter as tk
path, W, H, loghid, termhid = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4] == "1", sys.argv[5] == "1"
pm = load(path)
root = tk.Tk()
p = pm.ControlPanel(root); root.geometry(f"{W}x{H}+0+0"); pump(root, 0.3)
if hasattr(p, "_update_terminal_visibility"):
    p._terminal_unlocked = True; p._update_terminal_visibility(); pump(root, 0.3)
    if bool(p._term_body.winfo_manager()) == termhid: p._toggle_terminal_visible()
if bool(p._log_body.winfo_manager()) == loghid: p._toggle_log_visible()
pump(root, 0.3)
n = [0]; orig = p._update_actions_scroll
def wrapped():
    n[0] += 1; orig()
p._update_actions_scroll = wrapped
menus = ["show_main_menu", "show_menu_connect", "show_menu_sleepwake", "show_menu_volume", "show_menu_power",
         "show_menu_heartbeat", "show_menu_sync", "show_menu_delete_video", "show_menu_debug",
         "show_menu_screencap", "show_menu_testing", "_render_testing_terminal", "_render_testing_power",
         "_render_testing_sleepwake", "_render_testing_snapshot"]
bad = 0
for m in menus:
    if not hasattr(p, m): continue
    print("..", m, flush=True)
    getattr(p, m)(); n[0] = 0
    pump(root, 0.4)
    calls = n[0]; n[0] = 0; pump(root, 0.3); later = n[0]
    need, vis = p.actions_container.winfo_reqwidth(), p._actions_canvas.winfo_width()
    osc = later > 3
    wide = need > vis + 1
    if osc or wide:
        bad += 1
    print("FAIL" if (osc or wide) else "ok  ", W, H, int(loghid), int(termhid), m, "calls", calls, "settled", later,
          "need", need, "vis", vis, flush=True)
print("CELL", W, H, int(loghid), int(termhid), "bad", bad, flush=True)
p._on_close()

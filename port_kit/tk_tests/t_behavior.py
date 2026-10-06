import os, sys, json, faulthandler
faulthandler.dump_traceback_later(150, exit=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["PATH"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakebin") + ":" + os.environ["PATH"]
from harness import load, pump, wait_for
import tkinter as tk
pm = load(os.environ.get("CXVR_PANEL", "cxvr_control_panel.py"))
PKG = pm.APP_PACKAGE
res = []
def ck(name, cond, extra=""):
    res.append(bool(cond)); print(("PASS" if cond else "FAIL"), name, "" if cond else extra, flush=True)
def widgets(w):
    for c in w.winfo_children():
        yield c; yield from widgets(c)
def btn(label, where=None):
    for c in widgets(where or p.actions_container):
        try:
            if str(c.cget("text")) == label and c.winfo_class() in ("TButton", "Button"): return c
        except Exception: pass
def texts(where=None):
    out = []
    for c in widgets(where or p.actions_container):
        try: out.append(str(c.cget("text")))
        except Exception: pass
    return out
root = tk.Tk(); p = pm.ControlPanel(root); root.geometry("920x760+0+0"); pump(root, 0.4)
ck("headtracking watchdog auto-starts", any("headtracking" in " ".join(map(str, c)).lower() or "stayAwake" in " ".join(map(str,c)) or "watchdog" in " ".join(map(str,c)).lower() for c in pm.spawned) or len(p.toggle_procs) >= 1, pm.spawned)
# main menu navigation
labels = ["Connect / Reconnect Headsets", "Sleep / Wake Management", "Volume Control", "Power Management",
          "Connection Heartbeat Monitor", "Content Sync", "Debug Tools", "Screen Capture", "Testing (not yet marked tested)"]
for lab in labels:
    p.show_main_menu(); pump(root, 0.1)
    b = btn(lab); ok = b is not None
    if ok: b.invoke(); pump(root, 0.15)
    ck(f"main menu opens: {lab}", ok and p.menu_title_var.get() != "Main Menu", p.menu_title_var.get())
p.show_main_menu(); pump(root, 0.1)
ck("Delete Video hidden from main menu while untested", btn("Delete Video") is None)
# show mode
cb = [c for c in widgets(p.actions_container) if c.winfo_class() == "TCheckbutton" and "SHOW MODE" in str(c.cget("text"))][0]
cb.invoke(); pump(root, 0.1)
ck("show mode on writes file", pm.SHOW_MODE_FILE.exists())
cb.invoke(); pump(root, 0.1)
ck("show mode off removes file", not pm.SHOW_MODE_FILE.exists())
# log hide persistence
p._log_toggle_btn.invoke(); pump(root, 0.1)
ck("log hide persisted", json.load(open(pm.CONFIG_FILE)).get("log_hidden") is True)
p._log_toggle_btn.invoke(); pump(root, 0.1)
# popup watchdog via real ToggleButton, no package prompt
p.show_menu_sleepwake(); pump(root, 0.2)
pm.dialogs.clear(); pm.spawned.clear()
tb = p.toggle_buttons.get("popupWatchdog")
ck("popup watchdog row present", tb is not None, list(p.toggle_buttons))
import threading as _th
_real_thread = _th.Thread
class _NoThread:
    def __init__(self, *a, **k): pass
    def start(self): pass
pm.threading.Thread = _NoThread
tb.invoke(); pump(root, 0.2)
ck("popup watchdog starts with built-in package, no dialog",
   pm.spawned and "--package" in pm.spawned[-1] and pm.spawned[-1][pm.spawned[-1].index("--package")+1] == PKG and not pm.dialogs, (pm.spawned, pm.dialogs))
ck("popup toggle relabels to Stop", str(tb.cget("text")) == "Stop")
tb.invoke(); pump(root, 0.2)
ck("popup toggle back to Start", str(tb.cget("text")) == "Start")
ck("stop signalled the watchdog's group", pm.killed and pm.killed[-1][1] is False)
pm.threading.Thread = _real_thread
# content sync: run buttons build commands, dry run carries flag
p.show_menu_sync(); pump(root, 0.2)
p.content_dir_var.set("/tmp"); p.remote_target_var.set("")
pm.spawned.clear()
btn("Dry Run").invoke(); pump(root, 0.3)
last = pm.spawned[-1] if pm.spawned else []
ck("Dry Run launches sync with --package and --dry-run", "--dry-run" in last and PKG in last, last)
wait_for(root, lambda: p.current_proc is None, 3)
# sync_in_progress brake cleared after the run
ck("sync_in_progress cleared after run", not pm.SYNC_IN_PROGRESS_FILE.exists())
# power confirmation names the headset (Testing page)
p._render_testing_power(); pump(root, 0.2)
p.power_target_var.set("172.16.16.28:5555")
pm.dialogs.clear(); pm.ASK = False
btn("Reboot").invoke(); pump(root, 0.2)
q = [d for d in pm.dialogs if d[0] == "askyesno"]
ck("reboot confirmation names the headset", q and "172.16.16.28:5555" in " ".join(map(str, q[-1][1])), q)
pm.ASK = True
# testing hub: every item has Open that renders something
p.show_menu_testing(); pump(root, 0.2)
names = [n for _, items in p._testing_items() for (_, n, _, _) in items]
ck("testing hub lists all gated items incl. Terminal", set(names) == {v[1] for v in pm.GATED_FEATURES.values()} and "Terminal" in names, names)
for group, items in p._testing_items():
    for key, name, dest, opener in items:
        opener(); pump(root, 0.15)
        ck(f"Testing opener renders: {name}", len(p.actions_container.winfo_children()) > 0)
# delete video: confirm names video and headset
p.show_menu_delete_video(); pump(root, 0.2)
p._delete_video_catalog = {"@Vid (abc)": "abc"}; p.delete_video_selection_var.set("@Vid (abc)")
p.delete_video_device_var.set("172.16.16.31:5555"); p.delete_video_dry_run_var.set(False)
pm.dialogs.clear(); pm.ASK = False
p.action_delete_video(); pump(root, 0.2)
q = [d for d in pm.dialogs if d[0] == "askyesno"]
ck("delete confirm names video + headset", q and "172.16.16.31:5555" in " ".join(map(str, q[-1][1])) and "Vid" in " ".join(map(str, q[-1][1])), q)
pm.ASK = True
# mark tested moves delete video to main menu
p._mark_tested("delete_video.delete", p.show_main_menu); pump(root, 0.2)
ck("Delete Video appears on main menu after Mark tested", btn("Delete Video") is not None)
# volume menu opens and stays responsive at small height with terminal shown (the old hang)
p._terminal_unlocked = True; p._update_terminal_visibility(); pump(root, 0.3)
if p._log_body.winfo_manager(): p._toggle_log_visible()
root.geometry("920x640"); pump(root, 0.3)
p.show_menu_volume()
import time; t0 = time.time(); pump(root, 0.8)
ck("Volume at 920x640 (log hidden, terminal shown) stays responsive", time.time() - t0 < 3)
p._on_close()
print("behavior", sum(res), "/", len(res))

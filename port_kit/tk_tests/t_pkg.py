import os, sys, json, faulthandler
faulthandler.dump_traceback_later(100, exit=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import load, pump
import tkinter as tk
old = load(os.environ.get("CXVR_PANEL_OLD", "cxvr_control_panel_before.py")); new = load(os.environ.get("CXVR_PANEL", "cxvr_control_panel.py"))
PKG = "com.CulturalXchange.BibleSchool"
res = []
def ck(name, cond, extra=""):
    res.append(bool(cond)); print(("PASS" if cond else "FAIL"), name, "" if cond else extra)
ck("constant", new.APP_PACKAGE == PKG)
ck("package gone from DEFAULT_CONFIG", "package" not in new.DEFAULT_CONFIG)
def make(pm):
    root = tk.Tk(); p = pm.ControlPanel(root); pump(root, 0.2)
    if hasattr(p, "package_var"): p.package_var.set(PKG)
    return root, p
def setup(p, rt, app_root, clean, cat, extra=()):
    p.content_dir_var.set("/tmp"); p.remote_target_var.set(rt)
    p.content_is_app_root_var.set(app_root); p.sync_clean_stale_var.set(clean); p.sync_check_catalog_var.set(cat)
    return p._sync_cmd(*extra)
norm = lambda c, pm: [x.replace(str(pm.SCRIPTS_CACHE_DIR), "S") for x in c] if c else c
ro, po = make(old); rn, pn = make(new)
for sc in [("", False, False, False), ("", True, True, True),
           (f"/sdcard/Android/data/{PKG}/files/Video", False, False, False),
           (f"/sdcard/Android/data/{PKG}/files/Video", False, True, False),
           (f"/sdcard/Android/data/{PKG}", True, True, True), ("/sdcard/somewhere", False, False, True)]:
    a = norm(setup(po, *sc), old); b = norm(setup(pn, *sc), new)
    ck(f"sync cmd identical {sc}", a == b and b is not None, f"\n old={a}\n new={b}")
ck("dry-run extra arg", setup(pn, "", False, False, False, ("--dry-run",))[-1] == "--dry-run")
new.dialogs.clear()
ck("other-package remote target refused", setup(pn, "/sdcard/Android/data/com.other.app/files/Video", False, False, False) is None
   and new.dialogs and new.dialogs[-1][0] == "showerror")
for p in (po, pn):
    p._delete_video_catalog = {"Vid": "abc123"}; p.delete_video_selection_var.set("Vid")
    p.delete_video_device_var.set("172.16.16.28:5555"); p.remote_target_var.set("")
dv_o = po._delete_video_cmd()[0]; dv_n = pn._delete_video_cmd()[0]
ck("delete cmd identical", norm(dv_o, old) == norm(dv_n, new), f"{dv_o}\n{dv_n}")
ck("delete cmd has package", dv_n[dv_n.index("--package") + 1] == PKG)
class B:
    def configure(self, **k): pass
    config = configure
for name in ("action_toggle_popup_watchdog", "action_toggle_overheat_watchdog", "action_toggle_blackscreen_probe"):
    for p, pm in ((po, old), (pn, new)):
        pm.spawned.clear(); getattr(p, name)(B())
    a = [norm(c, old) for c in old.spawned]; b = [norm(c, new) for c in new.spawned]
    ck(f"{name} identical & has package", a == b and b and PKG in b[0], f"{a}\n{b}")
pn.show_menu_sync(); pump(rn)
labels = []
def walk(w):
    for c in w.winfo_children():
        try: labels.append(str(c.cget("text")))
        except Exception: pass
        walk(c)
walk(pn.actions_container)
ck("no 'App package' field", "App package" not in labels)
ck("caption names built-in package", any(PKG in l and "built in" in l for l in labels))
cfg = json.load(open(new.CONFIG_FILE)); cfg["package"] = "com.wrong.app"; json.dump(cfg, open(new.CONFIG_FILE, "w"))
r3 = tk.Tk(); p3 = new.ControlPanel(r3); pump(r3, 0.2)
ck("warns about differing saved package", "com.wrong.app" in p3.log_text.get("1.0", "end"))
print("pkg", sum(res), "/", len(res))
for r, p in ((ro, po), (rn, pn), (r3, p3)): p._on_close()

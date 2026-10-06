#!/usr/bin/env python3
"""Runs every scenario in scenarios.py against one panel and writes what it did
as JSON: commands started (paths normalized), processes signalled, dialogs
(kind, title, text, answer), subprocess.run calls, config and sentinel-file
changes, the text added to the live log, and a snapshot of the panel's state.

  Tk:  xvfb-run -a -s "-screen 0 1600x1200x24" PY311 record.py --panel tk --file cxvr_control_panel.py --out tk.json
  Qt:  VENV_PY record.py --panel qt --file cxvr_control_panel_qt.py --out qt.json

--only NAME[,NAME...] runs a subset; --phase N skips scenarios for later phases."""
import argparse
import json
import os
import shutil
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "common"))


def load_adapter(kind, path):
    if kind == "tk":
        import harness_tk
        return harness_tk.TkPanel(path)
    import harness_qt
    return harness_qt.QtPanel(path)


def read_config(pm):
    try:
        return json.loads(pm.CONFIG_FILE.read_text())
    except Exception:
        return {}


def reset_config_dir(pm, sc):
    pm.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("config.json", "show_mode", "sync_in_progress"):
        try:
            (pm.CONFIG_DIR / name).unlink()
        except FileNotFoundError:
            pass
    for name in ("adb_debug_wrapper", "adb_debug_logs", "snapshots"):
        shutil.rmtree(pm.CONFIG_DIR / name, ignore_errors=True)
    if sc.get("config"):
        pm.CONFIG_FILE.write_text(json.dumps(sc["config"], indent=2))
    for name, present in (sc.get("sentinels") or {}).items():
        if present:
            (pm.CONFIG_DIR / name).write_text("enabled by scenario\n")


def config_changes(rec, before, after):
    changed = {}
    for key in sorted(set(before) | set(after)):
        if key in ("window_geometry", "dock_state"):
            continue   # the Qt window layout (plan 6.4) -- only written when the window closes
        if before.get(key, "<absent>") != after.get(key, "<absent>"):
            changed[key] = rec.norm(json.dumps(after.get(key, "<removed>"), sort_keys=True))
    return changed


def snapshot(ad, rec):
    p = ad.p
    state = {
        "title": p.menu_title_var.get(),
        "toggle_procs": sorted(p.toggle_procs),
        "bg_tasks": p.bg_tasks_var.get(),
        "status": {k: v.get() for k, v in sorted(p.status_vars.items())},
        "failed_flagged": ad.failed_flagged(),
        "running_one_shot": p.current_proc is not None,
        "switches": {k: b.cget("text") for k, b in sorted(p.toggle_buttons.items())},
        "show_mode": bool(p.show_mode_var.get()),
        "tested": sorted(p.tested_features),
        "volume_last": rec.norm(p.volume_last_var.get()) if hasattr(p, "volume_last_var") else None,
    }
    for name in ("visual_check_var", "volume_target_var", "volume_level_var", "power_target_var"):
        state[name] = getattr(p, name).get()
    return state


def run_step(ad, rec, step, extra):
    op, args = step[0], step[1:]
    p = ad.p
    if op == "open":
        ad.open(args[0])
    elif op == "click":
        ad.click(args[0], *(args[1:]))
    elif op == "click_in":
        ad.click_in(*args)
    elif op == "strip":
        ad.strip(args[0])
    elif op == "row":
        ad.row_click(*args)
    elif op == "toggle":
        ad.toggle(args[0])
    elif op == "type":
        ad.type_into(*args)
    elif op == "check":
        ad.check(*args)
    elif op == "choose":
        ad.choose(*args)
    elif op == "refresh":
        ad.refresh(args[0])
    elif op == "set":
        getattr(p, args[0]).set(args[1])
    elif op == "show_mode":
        ad.set_show_mode(args[0])
    elif op == "answer":
        rec.answers.extend(args)
    elif op == "files":
        rec.file_answers.extend(args)
    elif op == "devices":
        rec.devices = list(args[0])
        rec.devices_error = None
    elif op == "devices_error":
        rec.devices_error = OSError(args[0])
    elif op == "output":
        rec.next_outputs.append(list(args[0]))
    elif op == "hold":
        import threading
        rec.hold_next_run = True
        rec.hold_event = threading.Event()
        rec._hold_pending = True
    elif op == "release":
        rec.hold_event.set()
        deadline = time.time() + 10
        while time.time() < deadline and (p.current_proc is not None or not p.log_queue.empty()):
            ad.pump(0.05)
        ad.pump(0.25)
    elif op == "start_and_end_in_one_tick":
        # A watchdog whose process dies within one 100 ms log-pump tick of starting.
        ad.toggle(args[0], pump=False)
        key = args[0]
        proc = p.toggle_procs.get(key)
        if proc is not None:
            del p.toggle_procs[key]
            p.log_queue.put(("line", f"[{key} watchdog ended]"))
        ad.pump(0.3)
    elif op == "proc_ends":
        # Exactly what the toggle's reader thread does when its process exits by itself.
        key = args[0]
        proc = p.toggle_procs.get(key)
        if proc is not None:
            del p.toggle_procs[key]
            p.log_queue.put(("line", f"[{key} watchdog ended]"))
    elif op == "call":
        # Logic that has no page in the Qt panel yet (a later phase): called directly on
        # both panels, so the copied logic is still proven to behave the same through the
        # compatibility layer (variables, dialogs, spawning) before its page exists.
        getattr(p, args[0])(*args[1:])
        ad.pump(0.05)
    elif op == "setattr":
        setattr(p, args[0], args[1])
    elif op == "pump":
        ad.pump(0.3)
    elif op == "snap":
        what = args[0]
        if what == "actions":
            extra.append(("actions", p.menu_title_var.get(), sorted(map(list, ad.page_actions()))))
        elif what.startswith("picker:"):
            extra.append(("picker", what.split(":", 1)[1], ad.picker_values(what.split(":", 1)[1])))
        elif what == "nav":
            keys, _title = ad.nav_items()
            extra.append(("nav", keys))
        elif what == "strip":
            extra.append(("strip", sorted(ad.strip_enabled().items()), bool(p.show_mode_var.get())))
    else:
        raise ValueError(f"unknown step {step!r}")
    if getattr(rec, "_hold_pending", False) and op == "click":
        # a held run was started by this click: wait until its worker has spawned
        deadline = time.time() + 5
        while time.time() < deadline and p.current_proc is None:
            time.sleep(0.01)
        rec._hold_pending = False
        ad.pump(0.05)


def run_scenario(ad, sc):
    pm = ad.pm
    rec = ad.install_stubs()
    reset_config_dir(pm, sc)
    if sc.get("devices") is not None:
        rec.devices = list(sc["devices"])
    rec.ps_lines = [line.replace("<CFGDIR>", str(pm.CONFIG_DIR)) for line in sc.get("ps") or []]
    before = read_config(pm)
    result = {"name": sc["name"]}
    try:
        ad.start()
        result["startup"] = list(rec.events)
        rec.events.clear()
        log0 = ad.log_text()
        before = read_config(pm)
        sentinels0 = rec.sentinels()
        extra = []
        for step in sc["steps"]:
            run_step(ad, rec, step, extra)
        ad.pump(0.15)
        log1 = ad.log_text()
        result["events"] = list(rec.events)
        result["extra"] = extra
        result["log"] = rec.norm(log1[len(log0):] if log1.startswith(log0) else "<<log was cleared>>" + log1)
        result["config_changes"] = config_changes(rec, before, read_config(pm))
        result["sentinels"] = {"before": sentinels0, "after": rec.sentinels()}
        result["state"] = snapshot(ad, rec)
    except Exception:
        result["error"] = traceback.format_exc()
    finally:
        if rec.hold_event is not None:
            rec.hold_event.set()
        try:
            ad.stop()
        except Exception:
            result.setdefault("error", traceback.format_exc())
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", choices=("tk", "qt"), required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--phase", type=int, default=99)
    args = ap.parse_args()
    import scenarios
    wanted = set(filter(None, args.only.split(",")))
    selected = [s for s in scenarios.SCENARIOS if s["phase"] <= args.phase and (not wanted or s["name"] in wanted)]
    ad = load_adapter(args.panel, os.path.abspath(args.file))
    results = []
    t0 = time.time()
    for sc in selected:
        results.append(run_scenario(ad, sc))
        status = "ERROR" if "error" in results[-1] else "ok"
        print(f"[{args.panel}] {sc['name']}: {status}", flush=True)
        if status == "ERROR":
            print(results[-1]["error"], flush=True)
    extra = {}
    if args.panel == "qt":
        extra["thread_violations"] = list(ad.pm.THREAD_VIOLATIONS)
    with open(args.out, "w") as f:
        json.dump({"panel": args.panel, "file": os.path.basename(args.file), "results": results, **extra}, f,
                  indent=1, default=str)
    errors = sum(1 for r in results if "error" in r)
    print(f"[{args.panel}] {len(results)} scenarios in {time.time() - t0:.1f}s, {errors} errors -> {args.out}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()

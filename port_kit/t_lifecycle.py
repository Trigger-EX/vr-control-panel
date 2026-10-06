#!/usr/bin/env python3
"""Lifecycle tests with real processes: nothing the Qt panel started may be left
running after it closes -- however it closes.

Each case starts the real panel (its real main(), signal handlers and atexit
hook) as a child process, offscreen, with a temporary HOME and a fake adb that
reports one headset and hangs whenever it's asked to talk to it. The panel then
starts real work: the auto-started Headtracking watchdog, Heartbeat,
Stay-Awake and a one-shot Volume check (stuck in adb). The test notes the
session of every process the panel started, ends the panel one way or another,
and then looks for any process still in one of those sessions.

Cases: window closed; SIGTERM; SIGINT (Ctrl+C); SIGHUP; SIGTERM while a
confirmation dialog is open; SystemExit raised inside a Qt callback; and SIGKILL
(no cleanup can run -- the daemons' own --parent-pid check must end them).

usage: VENV_PY t_lifecycle.py QT_PANEL"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "cxvr_control_panel_qt.py")

DRIVER = r'''
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("cxvr_panel_under_test", sys.argv[1])
pm = importlib.util.module_from_spec(spec); spec.loader.exec_module(pm)
from PySide6.QtCore import QTimer
CASE, CLOSE_FILE = sys.argv[2], sys.argv[3]
orig_init = pm.ControlPanel.__init__

def patched(self, *a, **k):
    orig_init(self, *a, **k)
    def go():
        self.show_menu_heartbeat()
        self.toggle_buttons["heartbeat"].invoke()
        self.action_toggle_stayawake(None)
        self.show_menu_volume()
        [b for b in self.action_buttons if b.label() == "Check current volume"][0].invoke()
        QTimer.singleShot(1500, report)
    def report():
        info = {"pid": os.getpid(), "toggles": sorted(self.toggle_procs),
                "one_shot": self.current_proc is not None}
        print("READY " + json.dumps(info), flush=True)
    def poll():
        if os.path.exists(CLOSE_FILE):
            what = open(CLOSE_FILE).read().strip()
            os.unlink(CLOSE_FILE)
            if what == "dialog":
                self.action_kill_adb_server()   # a modal confirmation, left open
            elif what == "systemexit":
                sys.exit(3)
            else:
                self.close()
    self._lifecycle_timer = QTimer(self)
    self._lifecycle_timer.timeout.connect(poll)
    self._lifecycle_timer.start(100)
    QTimer.singleShot(300, go)

pm.ControlPanel.__init__ = patched
sys.argv = [sys.argv[1]]
code = pm.main()
print("MAIN RETURNED", code, flush=True)
sys.exit(code)
'''


def sid_of(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return int(f.read().rsplit(")", 1)[1].split()[3])
    except (OSError, IndexError, ValueError):
        return None


def all_pids():
    return [int(p) for p in os.listdir("/proc") if p.isdigit()]


def descendants(root):
    children = {}
    for pid in all_pids():
        try:
            with open(f"/proc/{pid}/stat") as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, IndexError, ValueError):
            continue
        children.setdefault(ppid, []).append(pid)
    out, todo = [], [root]
    while todo:
        for child in children.get(todo.pop(), []):
            out.append(child)
            todo.append(child)
    return out


def cmdline(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        return ""


def pgid_of(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return int(f.read().rsplit(")", 1)[1].split()[2])
    except (OSError, IndexError, ValueError):
        return None


def timeout_group(pid):
    """True if pid is in a process group led by a coreutils `timeout` (or is a zombie
    left by one -- empty cmdline)."""
    leader = pgid_of(pid)
    return leader is not None and (cmdline(leader).startswith("timeout ") or
                                   (cmdline(pid) == "" and cmdline(leader) == ""))


def run_case(case, action, adb_mode="hang", wait_exit=12, leftover_grace=0.5):
    home = tempfile.mkdtemp(prefix=f"cxvr_life_{case}_")
    close_file = os.path.join(home, "close_now")
    driver = os.path.join(home, "driver.py")
    with open(driver, "w") as f:
        f.write(DRIVER)
    env = dict(os.environ, HOME=home, QT_QPA_PLATFORM="offscreen", CXVR_FAKE_ADB_MODE=adb_mode,
               PATH=os.path.join(HERE, "fakebin_lifecycle") + os.pathsep + os.environ["PATH"])
    env.pop("DISPLAY", None)
    proc = subprocess.Popen([sys.executable, driver, PANEL, case, close_file], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            start_new_session=True)
    ready, lines = None, []
    deadline = time.time() + 30
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        lines.append(line.rstrip())
        if line.startswith("READY "):
            ready = json.loads(line[6:])
            break
    if ready is None:
        proc.kill()
        return False, f"panel never became ready: {lines[-8:]}"
    panel_sid = sid_of(proc.pid)
    sessions = {sid_of(p) for p in descendants(proc.pid)} - {panel_sid, None}
    started = {p: cmdline(p) for p in descendants(proc.pid)}
    names = sorted({os.path.basename(c.split()[1]) if len(c.split()) > 1 else c for c in started.values()
                    if ".sh" in c})
    want = 3 if adb_mode == "quick" else 4
    if len(sessions) < want:
        proc.kill()
        return False, f"expected >= {want} child sessions (3 watchdogs + a stuck one-shot), got {len(sessions)}: {names}"

    action(proc, close_file)
    exited = True
    try:
        proc.wait(timeout=wait_exit)
    except subprocess.TimeoutExpired:
        exited = False
    rest = proc.stdout.read() if exited else ""
    if not exited:
        proc.kill()
        proc.wait()
    time.sleep(leftover_grace)
    left = [p for p in all_pids() if sid_of(p) in sessions]
    # KNOWN LIMITATION (shared with the Tk panel, reported 27 Sep 2026): coreutils `timeout`
    # puts itself in a process group of its own, so kill_process_group() -- a killpg of the
    # script's group -- doesn't reach `timeout N adb ...` or its adb. They stay in the
    # script's session and end by themselves when their timeout runs out (20 s at most in
    # these scripts). Anything else left behind is a failure.
    bounded = [p for p in left if timeout_group(p)]
    unbounded = [p for p in left if p not in bounded]
    lingered = 0.0
    if bounded:
        t0 = time.time()
        while time.time() - t0 < 25 and any(sid_of(p) in sessions for p in bounded):
            time.sleep(0.25)
        lingered = time.time() - t0
    still = [p for p in all_pids() if sid_of(p) in sessions]
    for p in still:   # never leave them behind for the next case
        try:
            os.kill(p, signal.SIGKILL)
        except OSError:
            pass
    detail = f"{len(sessions)} child sessions ({', '.join(names)}); panel exit code {proc.returncode}"
    if bounded:
        detail += (f"; {len(bounded)} timeout-wrapped adb process(es) outlived the panel by "
                   f"{lingered:.0f} s (known limitation)")
    if not exited:
        return False, "panel didn't exit: " + detail
    if unbounded:
        return False, f"{len(unbounded)} process(es) left: " + "; ".join(cmdline(p)[:90] for p in unbounded[:6])
    if still:
        return False, f"{len(still)} timeout-wrapped process(es) didn't end within 25 s: " + detail
    if case in ("close", "sigterm", "sigint", "sighup", "dialog") and "MAIN RETURNED" not in rest:
        return False, "main() didn't return normally: " + rest[-300:]
    return True, detail


def close_window(proc, close_file):
    open(close_file, "w").close()


def send(sig, delay=0.0):
    def act(proc, _close_file):
        time.sleep(delay)
        os.kill(proc.pid, sig)
    return act


def trigger_then(what, sig):
    def act(proc, close_file):
        with open(close_file, "w") as f:
            f.write(what)
        time.sleep(1.0)
        if sig is not None:
            os.kill(proc.pid, sig)
    return act


CASES = [
    ("close", "window closed (as the X button does)", close_window, {}),
    ("sigterm", "SIGTERM", send(signal.SIGTERM), {}),
    ("sigint", "SIGINT / Ctrl+C", send(signal.SIGINT), {}),
    ("sighup", "SIGHUP", send(signal.SIGHUP), {}),
    ("dialog", "SIGTERM while a confirmation dialog is open", trigger_then("dialog", signal.SIGTERM), {}),
    ("systemexit", "SystemExit inside a Qt callback", trigger_then("systemexit", None), {}),
    ("sigkill", "SIGKILL -- no cleanup possible; the daemons' --parent-pid check ends them",
     send(signal.SIGKILL), {"adb_mode": "quick", "leftover_grace": 8.0}),
]


def main():
    results = []
    for case, title, action, opts in CASES:
        ok, detail = run_case(case, action, **opts)
        results.append(ok)
        print(("PASS " if ok else "FAIL ") + f"{title}: {detail}", flush=True)
    print(f"lifecycle {sum(results)} / {len(results)}")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

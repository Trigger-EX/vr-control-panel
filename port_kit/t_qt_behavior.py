#!/usr/bin/env python3
"""Qt-only behaviour checks -- things the differential suite can't see because
they have no Tk counterpart (switches, docks, the log pump, bindings, the
default button of a confirmation). Offscreen, with the shared stubs; clicks go
through real widgets.

usage: VENV_PY t_qt_behavior.py QT_PANEL"""
import gc
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "common"))
import harness_qt  # noqa: E402  (sets HOME, offscreen, main-thread assertions)
import record  # noqa: E402

results = []


def ck(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -- {detail}"), flush=True)


ad = harness_qt.QtPanel(sys.argv[1] if len(sys.argv) > 1 else "cxvr_control_panel_qt.py")
pm = ad.pm
from PySide6.QtCore import QPoint, QPointF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402

app = ad.app


def fresh(config=None, sentinels=None, size=(1280, 860)):
    if ad.p is not None:
        try:
            ad.stop()
        except Exception:
            pass
    rec = ad.install_stubs()
    record.reset_config_dir(pm, {"config": config, "sentinels": sentinels})
    ad.start(size=size)
    return rec


def settle(n=6):
    for _ in range(n):
        app.processEvents()


# ------------------------------------------------------------------ ToggleSwitch
changes = []
sw = pm.ToggleSwitch(running=False, on_change=changes.append, command=lambda: None)
sw.click()
ck("switch doesn't flip itself when its action refuses to start", sw.cget("text") == "Start" and not changes)
sw.configure(text="Stop Popup/Crash Recovery Watchdog")
ck("configure(text='Stop ...') -> running, row told", sw.cget("text") == "Stop" and changes == [True])
sw.configure(text=sw.cget("text").replace("Stop", "Start"))
ck("the Tk relabel idiom .replace('Stop','Start') works", sw.cget("text") == "Start" and changes == [True, False])
sw.deleteLater()

# ------------------------------------------------------------------ dialogs (real QMessageBox)
seen = {}


def inspect_and(key_to_press):
    def run():
        box = QApplication.activeModalWidget()
        if isinstance(box, QMessageBox):
            seen["default"] = box.defaultButton() is box.button(QMessageBox.StandardButton.No)
            seen["escape"] = box.escapeButton() is box.button(QMessageBox.StandardButton.No)
            seen["plain"] = box.textFormat() == Qt.TextFormat.PlainText
            seen["text"] = box.text()
            QTest.keyClick(box, key_to_press)
        else:
            seen["box"] = repr(box)
            QTimer.singleShot(50, run)
    return run


shim = pm._MessageBoxShim()
QTimer.singleShot(50, inspect_and(Qt.Key.Key_Return))
answer = shim.askyesno("Confirm Reboot", "This reboots <b>EVERY</b> connected headset. Continue?")
ck("confirmation defaults to No: Enter answers No", answer is False and seen.get("default"), seen)
ck("Escape is No too", seen.get("escape"), seen)
ck("dialog text is plain text (no accidental HTML)", seen.get("plain") and "<b>" in seen.get("text", ""), seen)
seen.clear()
QTimer.singleShot(50, inspect_and(Qt.Key.Key_Y))
ck("Y answers Yes", shim.askyesno("Q", "Continue?") is True, seen)

# ------------------------------------------------------------------ Var bindings
v = pm.StringVar(value="8")
e = pm.Entry(v)
QTest.keyClicks(e, "5")
ck("typing into an Entry updates its StringVar", v.get() == "85", v.get())
v.set("12")
ck("setting the StringVar updates the Entry", e.text() == "12")
b = pm.BooleanVar(value="yes")
ck("BooleanVar coerces like Tcl getboolean", b.get() is True and pm.BooleanVar(value="0").get() is False)
cv = pm.StringVar(value=pm.ALL_DEVICES_LABEL)
combo = pm.Combo(cv, [pm.ALL_DEVICES_LABEL])
cv.set("172.16.16.28:5555")
ck("a value not in the list is still shown (as Tk's readonly Combobox did)",
   combo.currentIndex() == -1 and combo.placeholderText() == "172.16.16.28:5555")
combo.configure(values=[pm.ALL_DEVICES_LABEL, "172.16.16.28:5555"])
ck("configure(values=...) reselects the variable's value", combo.currentText() == "172.16.16.28:5555")
combo.choose(pm.ALL_DEVICES_LABEL)
ck("picking an entry sets the variable", cv.get() == pm.ALL_DEVICES_LABEL)
before = combo.currentIndex()
ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120), Qt.MouseButton.NoButton,
                 Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
QApplication.sendEvent(combo, ev)
ck("mouse wheel over a headset picker never changes the target", combo.currentIndex() == before and cv.get() == pm.ALL_DEVICES_LABEL)
sv = pm.StringVar(value="14")
spin = pm.SpinEntry(sv, 0, 15)
spin.up_button.click(); spin.up_button.click()
ck("+ steps and clamps at the top (15)", sv.get() == "15", sv.get())
sv.set("abc"); spin.down_button.click()
ck("- on text that isn't a number starts from the top", sv.get() == "15", sv.get())
spin.entry.setFocus(); QTest.keyClick(spin.entry, Qt.Key.Key_Down)
ck("Down arrow in the field steps down", sv.get() == "14", sv.get())
tok = cv.trace_count()
combo.deleteLater(); e.deleteLater(); spin.deleteLater()
settle(); app.sendPostedEvents(None, 52); settle()  # 52 = QEvent.DeferredDelete
ck("a deleted widget's binding is removed from its variable", cv.trace_count() == tok - 1 and v.trace_count() == 0,
   (cv.trace_count(), v.trace_count()))

# ------------------------------------------------------------------ main-thread guard
guard_var = pm.StringVar(value="x")
guard_label = pm.Caption(var=guard_var)
err = []
def _try():
    try:
        guard_var.set("from worker")
    except AssertionError as exc:
        err.append(str(exc))


t = threading.Thread(target=_try)
t.start(); t.join()
ck("a widget-bound variable set from a worker thread is caught in tests", err and pm.THREAD_VIOLATIONS, err)
pm.THREAD_VIOLATIONS.clear()
guard_label.deleteLater()

# ------------------------------------------------------------------ the window
rec = fresh()
p = ad.p
ck("opens on Connect (plan D5)", p.menu_title_var.get() == "Connect / Reconnect Headsets"
   and p.nav_buttons["connect"].isChecked())
ck("headtracking watchdog auto-started", p.toggle_procs.get("htWatchdog") is not None)
ck("log records the Python, PySide6 and Qt versions",
   "PySide6" in ad.log_text() and "Qt " in ad.log_text() and sys.version.split()[0] in ad.log_text())
ck("dock panes have object names (needed to save the layout)",
   p.log_dock.objectName() == "logDock" and p.term_dock.objectName() == "terminalDock")
ck("Delete Video hidden from the sidebar while untested", not p.nav_buttons["delete_video"].isVisibleTo(p))
ck("Testing badge shows 7 untested", p._testing_badge.text() == "7" and p._testing_badge.isVisibleTo(p))
p._mark_tested("delete_video.delete", p.show_menu_testing)
settle()
ck("after Mark tested: Delete Video in the sidebar, badge 6",
   p.nav_buttons["delete_video"].isVisibleTo(p) and p._testing_badge.text() == "6")
ck("terminal pane hidden while terminal.shell is untested", not p.term_dock.isVisible()
   and not p._pane_toggles["terminalDock"].isVisibleTo(p))
p._mark_tested("terminal.shell", p.show_menu_testing)
settle()
ck("marking the terminal tested shows its pane", p.term_dock.isVisible() or not p.term_dock.isHidden())
p._unmark_tested("terminal.shell", p.show_menu_testing)
settle()
ck("unmarking hides it again", p.term_dock.isHidden() and not p._pane_toggles["terminalDock"].isVisibleTo(p))
ck("Interrupt script is never registered (always enabled)", p.interrupt_btn not in p.action_buttons)
ad.open("connect")
purge = [w for w in p.page.findChildren(pm.Button) if w.label().startswith("Purge")][0]
ck("an & in a label is shown, not turned into a shortcut", purge.text().startswith("Purge && Reconnect")
   and purge.label().startswith("Purge & Reconnect"))

# show mode
p.show_mode_switch.invoke(); settle()
ck("Show Mode on: file written, strip amber, banner shown",
   pm.SHOW_MODE_FILE.exists() and p.strip.property("showmode") is True and p.show_bar.isVisible())
p.show_mode_switch.invoke(); settle()
ck("Show Mode off: file removed, banner hidden", not pm.SHOW_MODE_FILE.exists() and not p.show_bar.isVisible())
pm.SHOW_MODE_FILE.write_text("set by the other panel\n")
ad.open("volume")
ck("opening a page picks up Show Mode set elsewhere", p.show_mode_var.get() is True and p.show_mode_switch.isChecked())
pm.SHOW_MODE_FILE.unlink()
ad.open("connect")

# strip layouts
p.resize(1300, 860); settle()
ck("wide window: one-row strip with the wordmark", p._strip_wide is True and p._brand.isVisible())
p.resize(960, 1040); settle()
ck("half-screen window (960): compact two-row strip", p._strip_wide is False and not p._brand.isVisible())
p.resize(800, 640); settle()
strip_right = max(w.geometry().right() for w in (p.stop_all_btn, p.interrupt_btn, p.kill_adb_btn))
ck("800 px: the strip's buttons fit inside the window", strip_right <= p.strip.width(), (strip_right, p.strip.width()))
p.resize(1280, 860); settle()

# chips
p.bg_tasks_var.set("heartbeat, htWatchdog, popupWatchdog, stayAwake")
settle()
ck("background tasks shown as chips with friendly names",
   p._chips.names() == ["Heartbeat", "Headtracking", "Popup recovery", "Stay-Awake"])
p._update_bg_tasks_label(); settle()

# failed count flag
p._parse_and_show_summary("Connected & stable: 5\nFAILED to confirm: 2\n")
ck("a non-zero failed count is flagged", p.failed_value_label.value.property("warn") is True)
p._parse_and_show_summary("Connected & stable: 5\nFAILED to confirm: 0\n")
ck("... and unflagged at zero", p.failed_value_label.value.property("warn") is False)

# ------------------------------------------------------------------ log
p._clear_log()
p._append_log("[connect] 172.16.16.43:5555 FAILED to confirm")
p._append_log("headset confirmed")
p._append_log("plain")
doc = p.log_text.document()
colours = [doc.findBlockByNumber(i).begin().fragment().charFormat().foreground().color().name() for i in range(3)]
ck("log colours as in Tk (FAIL red, confirmed green, other plain)",
   colours == [pm.UI_LOG_FAIL.lower(), pm.UI_LOG_OK.lower(), pm.UI_CONSOLE_FG.lower()], colours)
ck("log text is each line plus a newline, like Tk", ad.log_text() == "[connect] 172.16.16.43:5555 FAILED to confirm\n"
   "headset confirmed\nplain\n")
p._clear_log()
total = pm.LOG_MAX_LINES + 600
for i in range(0, total, 300):
    p._append_log_lines([f"line {n}" for n in range(i, min(i + 300, total))])
kept = ad.log_text().splitlines()
ck(f"on-screen log keeps the last {pm.LOG_MAX_LINES} lines", doc.blockCount() <= pm.LOG_MAX_LINES + 1
   and len(kept) == pm.LOG_MAX_LINES and kept[-1] == f"line {total - 1}" and kept[0] == f"line {total - len(kept)}",
   (doc.blockCount(), len(kept), kept[0], kept[-1]))
p._clear_log()

# log pump under a flood
ticks, fired = [], []
orig_poll = p._poll_log_queue


def timed_poll():
    t0 = time.perf_counter()
    orig_poll()
    ticks.append(time.perf_counter() - t0)


p._pump_timer.timeout.disconnect()
p._pump_timer.timeout.connect(timed_poll)
for i in range(50000):
    p.log_queue.put(("line", f"[sync] 172.16.16.{i % 70}:5555 pushed chunk {i}"))
start = time.perf_counter()
probe = QTimer()
probe.timeout.connect(lambda: fired.append(time.perf_counter()))
probe.start(20)
while not p.log_queue.empty() and time.perf_counter() - start < 60:
    app.processEvents()
    time.sleep(0.005)
probe.stop()
drain = time.perf_counter() - start
worst_gap = max((b - a for a, b in zip(fired, fired[1:])), default=0)
ck("50,000-line burst drains in pieces (<= 2,000 lines per tick)", len(ticks) >= 25 and not p.log_queue.qsize(),
   (len(ticks), p.log_queue.qsize()))
ck(f"window stays responsive: worst tick {max(ticks) * 1000:.0f} ms, worst event gap {worst_gap * 1000:.0f} ms, "
   f"drained in {drain:.1f} s", max(ticks) < 0.5 and worst_gap < 0.6, (max(ticks), worst_gap))
p._pump_timer.timeout.disconnect()
p._pump_timer.timeout.connect(p._poll_log_queue)
p._clear_log()

# ------------------------------------------------------------------ page rebuild soak
gc.collect(); settle(); app.sendPostedEvents(None, 52); settle()
watched = [p.power_target_var, p.volume_target_var, p.volume_level_var, p.visual_check_var, p.menu_title_var,
           p.show_mode_var, p.bg_tasks_var] + list(p.status_vars.values())


def counts():
    app.sendPostedEvents(None, 52)
    settle(2)
    gc.collect()
    return [v.trace_count() for v in watched], len(p.findChildren(QWidget))


pages = ["connect", "volume", "power", "heartbeat", "testing", "testing_power", "sleepwake", "sync", "screencap"]
for key in pages:
    ad.open(key)
ad.open("volume")
base = counts()
for i in range(200):
    ad.open(pages[i % len(pages)])
ad.open("volume")
after = counts()
ck("200 page switches: no binding or widget build-up", base == after, (base, after))

# ------------------------------------------------------------------ docks and window state
ad.open("connect")
p.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, p.log_dock)
p.resize(1111, 777)
settle()
p.close()
settle()
cfg = json.loads(pm.CONFIG_FILE.read_text())
ck("closing saves window_geometry and dock_state", cfg.get("window_geometry") and cfg.get("dock_state"))
ck("closing cleaned up the auto-started watchdog", any(e[0] == "kill" and "massConnect" in e[1] and e[2]
                                                      for e in ad.rec.events), ad.rec.events[-3:])
ad.p.deleteLater()
ad.p = None
rec = ad.install_stubs()
ad.start(size=(900, 700))  # start() resizes -- restore wins because restoreGeometry ran first? check area only
p = ad.p
ck("a new panel restores the dock arrangement (log on the right)",
   p.dockWidgetArea(p.log_dock) == Qt.DockWidgetArea.RightDockWidgetArea)
p.log_dock.close()
settle()
ck("closing the log pane unchecks its sidebar toggle", not p._pane_toggles["logDock"].isChecked())
p._pane_toggles["logDock"].click()
settle()
ck("the sidebar toggle brings it back", p.log_dock.isVisible() and p._pane_toggles["logDock"].isChecked())
p.log_dock.setFloating(True)
p.log_dock.move(20000, 20000)
settle()
p.close()
settle()
ad.p.deleteLater()
ad.p = None
ad.install_stubs()
ad.start()
p = ad.p
screens = [s.availableGeometry() for s in QApplication.screens()]
ck("a pane floated onto a monitor that's gone comes back where it can be reached",
   not p.log_dock.isFloating() or any(a.intersects(p.log_dock.geometry()) for a in screens), p.log_dock.geometry())
cfg = json.loads(pm.CONFIG_FILE.read_text())
cfg["dock_state"] = "not base64 at all!!"
cfg["window_geometry"] = 42
pm.CONFIG_FILE.write_text(json.dumps(cfg))
p.close()
settle()
ad.p.deleteLater()
ad.p = None
pm.CONFIG_FILE.write_text(json.dumps(cfg))
ad.install_stubs()
try:
    ad.start()
    ok = ad.p.log_dock is not None
except Exception as exc:
    ok = False
    print(exc)
ck("a damaged saved layout is ignored, not fatal", ok)

# ------------------------------------------------------------------ safe preview (--screenshot)
ad.stop()
ad.p = None
rec = ad.install_stubs()
record.reset_config_dir(pm, {})
safe = pm.ControlPanel(safe_preview=True)
settle()
ck("--screenshot mode starts nothing and runs no ps", not [e for e in rec.events if e[0] in ("spawn", "run")],
   rec.events)
safe.close()
settle()
ck("--screenshot mode saves nothing", not pm.CONFIG_FILE.exists())
safe.deleteLater()

# the terminal pane must not cover the live log when the panel opens
ad.install_stubs()
record.reset_config_dir(pm, {"config": {"tested_features": ["terminal.shell"]}})
ad.start()
from PySide6.QtWidgets import QTabBar  # noqa: E402
bars = [b for b in ad.p.findChildren(QTabBar) if b.count() == 2]
front = bars[0].tabText(bars[0].currentIndex()) if bars else None
ck("terminal pane present at startup but behind the live log (Qt parks a back tab off-screen)",
   not ad.p.term_dock.isHidden() and front == "Live log"
   and not ad.p.term_dock.geometry().intersects(ad.p.rect()), (front, ad.p.term_dock.geometry()))

# an error inside a Qt callback reaches the live log (a double-clicked panel has no terminal)
pm._active_panel = ad.p
old_hook = sys.excepthook
sys.excepthook = pm._report_unhandled
QTimer.singleShot(0, lambda: 1 / 0)
import io, contextlib
with contextlib.redirect_stderr(io.StringIO()):
    ad.pump(0.3)
sys.excepthook = old_hook
pm._active_panel = None
ck("an unexpected error in a callback shows up in the live log",
   "[panel error -- please report this]" in ad.log_text() and "ZeroDivisionError" in ad.log_text())
ck("... and the panel keeps running", ad.p.isVisible() and ad.p._pump_timer.isActive())
ad.stop()
ad.p = None

ck("no widget was touched from a worker thread during these tests", not pm.THREAD_VIOLATIONS, pm.THREAD_VIOLATIONS)
print(f"qt behaviour {sum(results)} / {len(results)}")
sys.exit(0 if all(results) else 1)

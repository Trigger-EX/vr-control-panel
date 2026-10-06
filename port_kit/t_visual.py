#!/usr/bin/env python3
"""Layout checks and screenshots: every page and state ported so far, at the
plan's sizes (800x640 minimum, 960x1040 the show layout, 1920x1040 maximized).
Fails if any page needs sideways scrolling, or if anything in the top strip or
the sidebar is cut off. Screenshots go to OUT_DIR for a person to look at.

usage: VENV_PY t_visual.py QT_PANEL OUT_DIR [WxH ...]
       QT_SCALE_FACTOR=1.25 VENV_PY t_visual.py QT_PANEL OUT_DIR 800x640 1536x832   (125 % scaling)"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "common"))
import harness_qt  # noqa: E402
import record  # noqa: E402

panel_path, out_dir = sys.argv[1], sys.argv[2]
sizes = [tuple(int(v) for v in s.split("x")) for s in sys.argv[3:]] or [(800, 640), (960, 1040), (1920, 1040)]
scale = os.environ.get("QT_SCALE_FACTOR", "1")
os.makedirs(out_dir, exist_ok=True)
ad = harness_qt.QtPanel(panel_path)
pm = ad.pm
from PySide6.QtWidgets import QLabel, QWidget  # noqa: E402

ALL = ["power.reboot", "power.poweroff", "sleepwake.overheat_watchdog", "sleepwake.blackscreen_probe",
       "delete_video.delete", "debug.capture_snapshot", "terminal.shell"]
# (name, config, sentinels, what to do once the panel is up)
STATES = [
    ("connect", None, None, lambda: ad.open("connect")),
    ("volume", None, None, lambda: (ad.open("volume"), ad.refresh("volume_target_var"))),
    ("power_untested", None, None, lambda: ad.open("power")),
    ("power_tested", {"tested_features": ["power.reboot", "power.poweroff"]}, None, lambda: ad.open("power")),
    ("heartbeat_running", None, None, lambda: (ad.open("heartbeat"), ad.toggle("heartbeat"))),
    ("testing_hub", None, None, lambda: ad.open("testing")),
    ("testing_hub_empty", {"tested_features": ALL}, None, lambda: ad.open("testing")),
    ("testing_power", None, None, lambda: ad.open("testing_power")),
    ("placeholder_sleepwake", None, None, lambda: ad.open("sleepwake")),
    ("show_mode_terminal_tabs", {"tested_features": ["terminal.shell", "delete_video.delete"]}, {"show_mode": True},
     lambda: (ad.open("volume"), ad.p.bg_tasks_var.set("heartbeat, htWatchdog, popupWatchdog, stayAwake"),
              ad.p._parse_and_show_summary("Connected & stable: 68\nFixed & confirmed this run: 5\n"
                                           "FAILED to confirm: 2\nTOTAL stable with fix applied: 70 / 70"))),
]

results = []


def ck(name, ok, detail=""):
    results.append(bool(ok))
    if not ok:
        print(f"FAIL {name}  -- {detail}", flush=True)


def inside(child, container):
    rect = child.rect().translated(child.mapTo(container, child.rect().topLeft()))
    return rect.left() >= 0 and rect.right() <= container.width() + 1, rect


for (w, h) in sizes:
    for name, config, sentinels, action in STATES:
        if ad.p is not None:
            ad.stop()
        ad.install_stubs()
        record.reset_config_dir(pm, {"config": config, "sentinels": sentinels})
        ad.start(size=(w, h))
        action()
        ad.pump(0.2)
        p = ad.p
        tag = f"{name} @ {w}x{h} (scale {scale})"
        bar = p.page_scroll.horizontalScrollBar()
        ck(f"{tag}: no sideways scrolling", bar.maximum() == 0 and not bar.isVisible(),
           f"horizontal range {bar.maximum()}")
        view = p.page_scroll.viewport()
        wide = [c for c in p.page.findChildren(QWidget) if c.isVisible() and not inside(c, view)[0]]
        ck(f"{tag}: nothing on the page wider than the view", not wide,
           [(type(c).__name__, getattr(c, "text", lambda: "")()[:30], inside(c, view)[1]) for c in wide[:4]])
        clipped = [c for c in p.strip.findChildren(QWidget) if c.isVisible() and c.parent() is not None
                   and not inside(c, p.strip)[0]]
        ck(f"{tag}: top strip fits", not clipped,
           [(type(c).__name__, getattr(c, "text", lambda: "")()[:20]) for c in clipped[:4]])
        side = p.sidebar_dock.widget()
        cut = [lbl for lbl in side.findChildren(QLabel) if lbl.isVisible() and
               lbl.fontMetrics().horizontalAdvance(lbl.text().split("\n")[0]) > lbl.width() + 1 and lbl.text()]
        ck(f"{tag}: sidebar labels fit", not cut, [lbl.text() for lbl in cut[:4]])
        nav_bottom = max(b.mapTo(side, b.rect().bottomLeft()).y() for b in p.nav_buttons.values() if b.isVisible())
        ck(f"{tag}: every sidebar item is on screen", nav_bottom <= side.height(), (nav_bottom, side.height()))
        ck(f"{tag}: log pane has room", p.log_dock.isHidden() or p.log_text.height() >= 50, p.log_text.height())
        suffix = "" if scale == "1" else f"_scale{scale}"
        p.grab().save(os.path.join(out_dir, f"{name}_{w}x{h}{suffix}.png"))

ad.stop()
print(f"visual {sum(results)} / {len(results)} (screenshots in {out_dir})")
sys.exit(0 if all(results) else 1)

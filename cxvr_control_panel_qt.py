#!/usr/bin/env python3
"""
cxvr_control_panel_qt.py -- the CXVR headset fleet control panel, rebuilt in
PySide6 (Qt). This is the port of cxvr_control_panel.py (Tkinter); until the
port is finished and has passed a rehearsal with the fleet, the Tkinter file
stays the production tool. Both read and write the same settings in
~/.cxvr_control_panel/, so going back is just a matter of starting the other one.

What is carried over unchanged (and checked by the port kit's integrity test):
  * every embedded script, byte for byte, in EMBEDDED_SCRIPTS;
  * the constants, the process helpers and the terminal backend;
  * all the logic inside ControlPanel below the line that says so -- every
    action, command builder, confirmation and safety check -- character for
    character, apart from three mechanical substitutions (tk.StringVar ->
    StringVar, tk.BooleanVar -> BooleanVar, tk.TclError -> RuntimeError).
What is new: the window, the pages and the small compatibility layer that lets
that logic run on Qt (settings variables, message boxes, Start/Stop switches).

Starting it: double-click it in the file manager, or run it with any Python 3.
If that Python doesn't have PySide6 (the system one usually doesn't), the file
starts itself again with ~/.pyvenv/bin/python, or with $CXVR_QT_PYTHON if set.

For support only:  --screenshot DIR  renders the main pages to PNG files
without starting anything (no watchdogs, no adb), then exits.
"""

import atexit
import functools
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
import queue
import select


def _relaunch_with_venv_python():
    """Double-clicking this file in a file manager starts it with whatever Python
    the desktop picks -- normally the system one, which doesn't have PySide6.
    When that happens, start this same file again with the Python in ~/.pyvenv
    (or $CXVR_QT_PYTHON), which does.

    A venv's bin/python is a symlink to the system Python, so candidates are
    compared by where they live, never by the binary they resolve to. The
    CXVR_RELAUNCHED flag makes sure this re-launches at most once."""
    try:
        import PySide6
    except ImportError:
        PySide6 = None
    if PySide6 is not None:
        os.environ.pop("CXVR_RELAUNCHED", None)   # don't leak the flag to anything started from here
        return
    here = os.path.abspath(__file__)
    current = os.path.abspath(sys.executable)
    if not os.environ.get("CXVR_RELAUNCHED"):
        for candidate in (os.environ.get("CXVR_QT_PYTHON", ""), os.path.expanduser("~/.pyvenv/bin/python")):
            if candidate and os.path.abspath(candidate) != current and os.access(candidate, os.X_OK):
                os.environ["CXVR_RELAUNCHED"] = "1"
                os.execv(candidate, [candidate, here] + sys.argv[1:])
    message = (f"PySide6 isn't available to the Python that started this file:\n{sys.executable}\n\n"
               f"The CXVR control panel (Qt) normally runs with ~/.pyvenv/bin/python. Install PySide6 there with\n"
               f"    ~/.pyvenv/bin/pip install PySide6\n"
               f"or set CXVR_QT_PYTHON to a Python that has it.\n\n"
               f"The Tkinter panel (cxvr_control_panel.py) doesn't need PySide6 and still works.")
    print(message, file=sys.stderr)
    if os.environ.get("DISPLAY") and not os.environ.get("CXVR_NO_DIALOG"):
        try:   # launched from a file manager there's no terminal, so say it in a window too
            import tkinter
            from tkinter import messagebox as tk_messagebox
            root = tkinter.Tk()
            root.withdraw()
            tk_messagebox.showerror("CXVR", message)
            root.destroy()
        except Exception:
            pass
    sys.exit(1)


if __name__ == "__main__":
    _relaunch_with_venv_python()

# PySide6 is imported only here, after the relaunch above has had its chance.
from PySide6 import __version__ as PYSIDE6_VERSION
from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt, QTimer, qVersion
from PySide6.QtGui import QColor, QFont, QPainter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QBoxLayout, QButtonGroup, QCheckBox, QComboBox, QDockWidget, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)
from shiboken6 import isValid as _qt_alive


APP_DIR = Path(__file__).resolve().parent

# The Headjack app's Android package ID. Android treats this as the app's permanent
# identity: an app update can never change it (a different ID is a different app, installed
# side by side). It would only change if the app were rebuilt as a brand-new Headjack app.
# Confirmed with `adb shell pm list packages` on a fleet headset. Everything that needs the
# package (content sync, delete video, the watchdogs and the probe) reads it from here.
APP_PACKAGE = "com.CulturalXchange.BibleSchool"
CONFIG_DIR = Path.home() / ".cxvr_control_panel"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Label used by every "which headset?" dropdown, so the panel has one spelling
# of "all of them" rather than a different string per menu.
ALL_DEVICES_LABEL = "ALL CONNECTED HEADSETS"

# Two independent brakes on automated corrective actions, deliberately
# implemented as plain files rather than in-process state: the watchdog
# daemons are separate processes, and a brake that needs a daemon restart to
# take effect is useless in the middle of a show.
#   show_mode        -- operator has disabled automation during a performance.
#   sync_in_progress -- written by this panel while a content sync runs, so a
#                       recovery action can't inject input mid-push.
SHOW_MODE_FILE = CONFIG_DIR / "show_mode"
SYNC_IN_PROGRESS_FILE = CONFIG_DIR / "sync_in_progress"

SNAPSHOT_DIR = CONFIG_DIR / "snapshots"

# Kept identical to overheatWatchdog.py's own DEFAULT_MATCH_PATTERN. Broad on
# purpose: right for observing, wrong for acting, which is why arming is a
# separate explicit step.
DEFAULT_OVERHEAT_PATTERN = r"thermal|overheat|too hot|temperature|cooling|heat"

# Actions gated behind the Testing menu until the operator has confirmed each
# one against real hardware. Only features added or materially changed this
# session are listed here -- everything else (Connect, Sleep All/Wake All,
# Volume, the existing watchdogs, Content Sync, the rest of Debug Tools and
# Screen Capture) is untouched by this mechanism and always shows normally.
# key -> (category shown on the main Power/Sleep-Wake/etc. menu, button label)
GATED_FEATURES = {
    "power.reboot": ("Power Management", "Reboot"),
    "power.poweroff": ("Power Management", "Power Off"),
    "sleepwake.overheat_watchdog": ("Sleep / Wake Management", "Overheat Dismissal Watchdog"),
    "sleepwake.blackscreen_probe": ("Sleep / Wake Management", "Black-Screen Probe"),
    "delete_video.delete": ("Delete Video", "Delete Video"),
    "debug.capture_snapshot": ("Debug Tools", "Capture Diagnostic Snapshot"),
    "terminal.shell": ("Terminal", "Terminal"),
}
SCRIPTS_CACHE_DIR = CONFIG_DIR / "embedded_scripts"

# The one tunable you've actually changed between venues so far, hoisted out
# here so it's easy to find without digging through the embedded script text
# below. NOTE: this uses a plain string substitution (not .format()/f-string)
# because bash uses {} constantly (${d}, {1..999}, etc.) -- an f-string-style
# substitution would collide with that and corrupt the embedded script.
CXVR_SUBNET_PREFIX = "172.16.16"   # <-- edit this per venue, not the embedded text below

# Android's STREAM_MUSIC has traditionally used a 0-15 range (16 discrete
# levels) across nearly all stock/OEM builds -- this is a very long-standing
# platform default, though not confirmed specifically on these headsets. If
# a real reading ever shows a different range here, adjust this constant --
# it's only used for the relative "-2/-3/-4" presets now; "Max" targets
# each device's own reported ceiling directly (see volumeNormalize.sh's
# "max" keyword) rather than an assumed number, so it can't ever chase a
# target above what a given device can actually reach.
ASSUMED_MAX_LEVEL = 15

# scrcpy's default local tunnel port (27183) is shared across ALL instances
# unless told otherwise -- running many simultaneously (Capture All, Batch
# Preview) means they collide on that single port, causing "more than one
# device/emulator" / "connect: Connection refused" failures. scrcpy's -p/
# --port flag accepts a RANGE and automatically claims a free port within
# it per instance, which is exactly the documented fix for this. 100 ports
# is comfortably more than this fleet could ever open simultaneously.
SCRCPY_PORT_RANGE = "27183:27282"

# How long to wait for each scrcpy instance to confirm its connection
# (seeing its own "[server] INFO: Device:" line) before moving on to launch
# the next one, when opening several at once. Replaces an earlier blind
# fixed-delay stagger (first 0.4s, then 1.5s) that turned out not to be the
# right fix even at the larger value -- real logs showed later devices
# still failing with rapid repeated "Connection refused" regardless of how
# long the gap was, meaning it wasn't purely a timing/spacing issue.
# Waiting for actual confirmation (or this timeout) instead serializes only
# the genuinely sensitive setup window for each device, rather than
# guessing a duration that either wastes time or still isn't enough.
SCRCPY_READY_TIMEOUT = 8
# Small extra gap even after a device confirms ready, before starting the
# next -- cheap insurance on top of the confirmation-based wait above.
SCRCPY_INTER_LAUNCH_GAP = 0.3

# Capture All has no built-in limit on how many windows it opens -- fine
# for a handful of headsets, unusable for a 70-headset fleet (which would
# try to open 70 windows at once). Batch Preview exists specifically for
# that case (capped groups, auto-cycling); Capture All refuses above this
# and points there instead of silently opening some confusing subset.
SCREENCAP_MAX_PARALLEL = 4

# Named volume presets -- (label, target level counted UP FROM FLOOR), listed
# from loudest to quietest. All of these go through the same closed-loop
# measure/adjust/reverify --set pipeline (read real volume, correct exactly
# the difference, re-check, retry up to 5 rounds) -- not a blind command
# count, so a dropped keyevent over wireless ADB gets caught and corrected
# instead of silently leaving that headset at a different volume than the
# rest. Edit freely.
VOLUME_PRESETS = [
    ("Max", "max"),   # each device's own real reported ceiling, not a fixed guess
    ("-2", ASSUMED_MAX_LEVEL - 2),
    ("-3", ASSUMED_MAX_LEVEL - 3),
    ("-4", ASSUMED_MAX_LEVEL - 4),
    ("Mute", 0),
]

DEFAULT_CONFIG = {
    "content_dir": "",
    "remote_target": "",
    "visual_check": False,
    "last_volume_op": "",
}


# ==========================================================
# EMBEDDED SCRIPTS -- exact byte-for-byte copies of the tested
# standalone scripts, materialized to disk at startup and run
# exactly as before. Generated verbatim via repr(); nothing here
# was hand-transcribed or rewritten.
# ==========================================================

EMBEDDED_SCRIPTS = {
    'massConnect.sh': '#!/bin/bash\n# Reconnects only the headsets that actually need it -- never touches an\n# already-stable connection -- then applies the headtracking fix to every\n# device that needs it as soon as it\'s confirmed connected (sleeping once,\n# at ANY point after boot, prevents the bug for the rest of the session --\n# no need to wait for the ~3min window it normally appears at).\n#\n# Commands are sent by transport ID (`adb -t`), matching your proven\n# sleepAll.sh/wakeAll.sh, not by serial (`adb -s host:port`) -- serial-based\n# dispatch was silently dropping commands on some headsets. Wake is\n# burst-fired several times in quick succession per device, mirroring\n# wakeAll.sh\'s repeated-attempt cadence, since wake has been the flakier of\n# the two in practice.\n#\n# After waking, each device is confirmed (commands succeeded + still\n# reachable over adb); anything not confirmed gets the whole sleep/wake\n# cycle retried, up to 3 times, and anything still unconfirmed after that is\n# printed to the terminal as a clear failure so you know which headset(s)\n# need manual attention. This phase runs in the foreground (not detached) so\n# those live confirmations/failures show up in your terminal as they happen.\n# Keeps a persistent "known IPs" file so it doesn\'t need to brute-force scan\n# the subnet on every run.\n#\n# Also runnable as a --watchdog daemon -- but unlike a normal run, the\n# watchdog does NOT reconnect or scan for headsets at all. It only takes a\n# live snapshot of whatever\'s currently connected (a plain `adb devices`)\n# and checks/re-applies the headtracking fix on exactly that -- nothing\n# about connection state, WiFi policy, or the known-IPs file. This is what\n# actually solves the "reboot silently un-fixes a headset and nobody\n# notices" problem: rebootAll.sh (or a crash, or a manual power cycle) gives\n# a headset a new boot_id, so the very next watchdog cycle correctly detects\n# it as needing the fix again and re-applies it, typically within a minute,\n# with no operator action needed -- while staying a cheap, narrowly-scoped\n# check rather than repeating the whole connect machinery every cycle.\n#\n# --watchdog also waits for at least one headset to be connected before its\n# first check, so it\'s safe to start immediately at launch (e.g. from the\n# control panel) even before any headset has connected yet. The lock that\n# prevents overlapping adb-hammering runs is only held for the duration of\n# actual work (a manual run, or one watchdog cycle) -- not for the\n# watchdog\'s idle time between cycles -- so a default-on watchdog never\n# blocks you from running a manual Connect/Full Scan/Purge whenever you want.\n#\n# If a device\'s reachability check happens to flake right after an\n# otherwise-successful sleep/wake (a real possibility over wireless), its\n# boot_id never gets recorded, so without a cooldown the very next watchdog\n# cycle would try again -- and if it flakes again, again the cycle after\n# that, forever, which looks like the headset waking constantly for no\n# reason. COOLDOWN_SECONDS (only enforced by the watchdog, never by a\n# manual run) prevents that: a device that fails to confirm gets left alone\n# for a while before the watchdog tries it again, instead of being\n# re-attempted every single interval.\n#\n# This also directly addresses the "adb server goes rogue" problem: the old\n# version called `adb disconnect` (no args = disconnect EVERYTHING) and then\n# fired up to 256 near-simultaneous connect attempts. Tearing down healthy\n# connections and flooding the adb server that hard is a solid explanation\n# for it getting into a bad state. This version only clears connections that\n# are actually stuck, and throttles connect attempts instead of blasting\n# them all at once.\n#\n# Usage:\n#   ./massConnect.sh                # normal run: fix broken/missing only\n#   ./massConnect.sh --full-scan    # also brute-force scan the whole subnet\n#                                    # (useful if a headset\'s IP changed)\n#   ./massConnect.sh --purge        # old behavior: disconnect EVERYTHING,\n#                                    # ignore known_ips.txt, full rescan.\n#                                    # Use when you actually want a clean slate.\n#   ./massConnect.sh --visual-check  # pause 20s between sleep and wake so\n#                                    # you can visually confirm on the tablet\n#                                    # (off by default -- opt in when you want it)\n#   ./massConnect.sh --watchdog      # lightweight daemon: waits for at least\n#                                    # one headset, then rechecks/re-fixes\n#                                    # whatever\'s currently connected every\n#                                    # 60s (--watchdog-interval N to change).\n#                                    # Does NOT reconnect or scan -- run a\n#                                    # normal Connect for that separately.\n#\n# SUBNET_PREFIX is hardcoded below since you run your own router -- update\n# it if you ever change subnets.\n\nset -u\n\nSTATE_DIR="${HOME}/.cxvr_massconnect"\nKNOWN_IPS="$STATE_DIR/known_ips.txt"\nLOCK_FILE="$STATE_DIR/massconnect.lock"\nHEADTRACK_STATE_DIR="${HOME}/.cxvr_headtracking_fix"\nTABLET_CHECK_DELAY=20       # seconds between sleep and wake, for visually\n                             # confirming on the tablet -- OFF by default,\n                             # opt in with --visual-check\nSUBNET_PREFIX="__CXVR_SUBNET_PREFIX__"   # <-- edit CXVR_SUBNET_PREFIX near the top of this .py file instead\nCOOLDOWN_SECONDS=300        # if a WATCHDOG-triggered fix attempt fails to\n                             # confirm, wait this long before retrying that\n                             # device again, instead of re-attempting (and\n                             # re-waking it) every single watchdog cycle.\n                             # Manual runs ignore this and always try immediately.\nPORT=5555\nCONNECT_CONCURRENCY=20      # throttle instead of blasting all targets at once\nCONNECT_TIMEOUT=5\n\nmkdir -p "$STATE_DIR" "$HEADTRACK_STATE_DIR"\ntouch "$KNOWN_IPS"\n\n# --- prevent overlapping massConnect operations (a manual run and a\n# watchdog cycle, or two manual runs) from hammering the adb server at the\n# same time. The lock is only held for the DURATION of actual work, not for\n# the watchdog\'s idle time between cycles -- since the watchdog runs by\n# default now, holding this permanently (like the old single global flock\n# at the top of the script used to) would block every manual Connect/Full\n# Scan/Purge from ever running while the watchdog is alive.\n#\n# flock releases automatically when its holding process dies -- but every\n# backgrounded `( adb ... ) &` dispatch job in this script inherits fd 9\n# from the parent shell, so if one of those ever got orphaned (e.g. killed\n# out from under its parent by an Interrupt/Stop that didn\'t fully reap\n# every child), it could keep holding the OS-level lock even though nothing\n# visible is running anymore. To recover from that automatically instead of\n# staying stuck forever, the lock file also records its holder\'s PID; if\n# acquiring fails, we check whether that PID is actually still alive, and\n# if it\'s not, we break the lock by recreating the file (a fresh inode, so\n# any stale hold on the old one no longer matters) and try once more. ---\nacquire_lock() {\n    if ! command -v flock > /dev/null 2>&1; then\n        return 0   # flock unavailable -- fail open, same as the old behavior\n    fi\n\n    exec 9> "$LOCK_FILE"\n    if flock -n 9; then\n        echo $$ > "$LOCK_FILE.pid"\n        return 0\n    fi\n\n    holder_pid=""\n    [ -f "$LOCK_FILE.pid" ] && holder_pid=$(cat "$LOCK_FILE.pid" 2>/dev/null)\n    if [ -n "$holder_pid" ] && ! kill -0 "$holder_pid" 2>/dev/null; then\n        echo "note: stale lock detected (recorded holder pid $holder_pid is no longer running) -- breaking it"\n        exec 9>&-\n        rm -f "$LOCK_FILE" "$LOCK_FILE.pid"\n        exec 9> "$LOCK_FILE"\n        if flock -n 9; then\n            echo $$ > "$LOCK_FILE.pid"\n            return 0\n        fi\n    fi\n    return 1\n}\nrelease_lock() {\n    rm -f "$LOCK_FILE.pid" 2>/dev/null || true\n    exec 9>&- 2>/dev/null || true\n}\n\n# --- parse args ---\nFULL_SCAN=0\nPURGE=0\nVISUAL_CHECK=0\nWATCHDOG=0\nWATCHDOG_INTERVAL=60\nPARENT_PID=""\nwhile [ $# -gt 0 ]; do\n    case "$1" in\n        --full-scan) FULL_SCAN=1 ;;\n        --purge) PURGE=1; FULL_SCAN=1 ;;\n        --visual-check) VISUAL_CHECK=1 ;;\n        --watchdog) WATCHDOG=1 ;;\n        --watchdog-interval) shift; WATCHDOG_INTERVAL="$1" ;;\n        --parent-pid) shift; PARENT_PID="$1" ;;\n        *) echo "unknown argument: $1 (ignored)" ;;\n    esac\n    shift\ndone\n\n# Self-terminate if our parent (the control panel) is no longer running --\n# hardens against exactly the failure mode that caused headsets to be woken\n# by an orphaned watchdog that outlived the app closing, however that\n# happened (crash, force-quit, anything short of this process itself being\n# killed). Not monitored (always reports alive) if --parent-pid was never\n# passed, e.g. running this by hand from a terminal.\nparent_alive() {\n    [ -z "$PARENT_PID" ] && return 0\n    kill -0 "$PARENT_PID" 2>/dev/null\n}\n\n# Sleeps in small chunks, checking parent liveness between each, so an\n# orphaned watchdog dies within seconds of its parent going away instead of\n# waiting out the full (possibly long) interval first. Returns 1 (and stops\n# early) if the parent died mid-sleep.\ninterruptible_sleep() {\n    local total="$1" elapsed=0 chunk remaining\n    while [ "$elapsed" -lt "$total" ]; do\n        parent_alive || return 1\n        remaining=$((total - elapsed))\n        chunk=5\n        [ "$remaining" -lt "$chunk" ] && chunk="$remaining"\n        sleep "$chunk"\n        elapsed=$((elapsed + chunk))\n    done\n    return 0\n}\n\nbuild_transport_map() {\n    transport_map_file=$(mktemp)\n    timeout 10 adb devices -l | awk \'NR>1 && $2=="device" {\n        for (i=3;i<=NF;i++) if ($i ~ /^transport_id:/) { split($i,a,":"); print $1 "\\t" a[2] }\n    }\' > "$transport_map_file"\n}\nget_tid() { awk -F\'\\t\' -v s="$1" \'$1==s {print $2; exit}\' "$transport_map_file"; }\n\napply_headtracking_fix() {\n# $1 = "1" when called from the watchdog (respect cooldown on repeated\n# confirm-failures); unset/anything else = manual run (always try immediately)\nrespect_cooldown="${1:-0}"\n# --- figure out which devices need the headtracking fix. No wait needed --\n# sleeping once, at any point after boot, prevents the bug for the rest of\n# the session, so we fire as soon as a device is confirmed connected. ---\nfix_map_file=$(mktemp)\nalready_fixed_count=0\nno_bootid_count=0\nno_tid_count=0\ncooldown_skipped_count=0\nconfirmed_this_run=0\nfailed_this_run=0\ndetect_map_file=""\nfor d in $connected_good; do\n    tid=$(get_tid "$d")\n    if [ -z "$tid" ]; then\n        echo "[$d] could not resolve transport id -- skipping auto-fix"\n        no_tid_count=$((no_tid_count + 1))\n        continue\n    fi\n    safe_name=$(echo "$d" | tr -c \'a-zA-Z0-9\' \'_\')\n    detect_map_file="${detect_map_file:-$(mktemp)}"\n    echo "$d\t$tid\t$safe_name" >> "$detect_map_file"\ndone\n\n# --- read every device\'s boot_id (and uptime, where relevant) IN PARALLEL.\n# This used to be a single sequential loop -- with a 10s timeout per call\n# and up to 73 devices, a handful of slow/unresponsive ones could add up\n# to minutes of pure sequential waiting before the fix step even started,\n# which is almost certainly what looked like "everything is sequential"\n# and plausibly what was starving a concurrently-run Sleep All of adb\n# server attention. Detection now happens for every device at once, in\n# the background; only the (fast, local, no network calls) bookkeeping\n# below -- logging and cooldown -- stays sequential, since that\'s cheap. ---\nscratch_detect=$(mktemp -d)\nif [ -n "${detect_map_file:-}" ]; then\n    while IFS=$\'\\t\' read -r d tid safe_name; do\n        (\n            boot_id=$(timeout 10 adb -t "$tid" shell cat /proc/sys/kernel/random/boot_id 2>/dev/null | tr -d \'\\r\\n\')\n            if [ -z "$boot_id" ]; then\n                echo "no_bootid" > "$scratch_detect/$safe_name.result"\n                exit 0\n            fi\n            state_file="$HEADTRACK_STATE_DIR/$safe_name"\n            last_fixed_boot_id=""\n            [ -f "$state_file" ] && last_fixed_boot_id=$(cat "$state_file")\n            if [ "$boot_id" = "$last_fixed_boot_id" ]; then\n                echo "already_fixed" > "$scratch_detect/$safe_name.result"\n                exit 0\n            fi\n            uptime_s=""\n            if [ -n "$last_fixed_boot_id" ]; then\n                uptime_s=$(timeout 10 adb -t "$tid" shell cat /proc/uptime 2>/dev/null | cut -d\'.\' -f1)\n            fi\n            echo "needs_fix\t$boot_id\t$last_fixed_boot_id\t$uptime_s" > "$scratch_detect/$safe_name.result"\n        ) &\n    done < "$detect_map_file"\n    wait\nfi\n\n# --- sequential collection: fast, local file reads only, no network calls ---\nif [ -n "${detect_map_file:-}" ]; then\n    while IFS=$\'\\t\' read -r d tid safe_name; do\n        result_file="$scratch_detect/$safe_name.result"\n        result=$(cat "$result_file" 2>/dev/null)\n        rm -f "$result_file"\n\n        case "$result" in\n            no_bootid|"")\n                echo "[$d] could not read boot_id -- skipping auto-fix"\n                no_bootid_count=$((no_bootid_count + 1))\n                continue ;;\n            already_fixed)\n                already_fixed_count=$((already_fixed_count + 1))\n                continue ;;\n        esac\n\n        IFS=$\'\\t\' read -r _ boot_id last_fixed_boot_id uptime_s <<< "$result"\n\n        # A real reboot resets uptime to near-zero. If boot_id changed but the\n        # device has actually been running for a long time, that\'s evidence\n        # boot_id itself isn\'t as stable on this build as it should be -- log\n        # it plainly either way so a pattern of "boot_id changed, uptime high"\n        # is visible in the log rather than silently treated the same as a\n        # genuine reboot.\n        if [ -n "$last_fixed_boot_id" ]; then\n            if [ -n "$uptime_s" ] && [ "$uptime_s" -gt 300 ] 2>/dev/null; then\n                echo "[$d] boot_id changed ($last_fixed_boot_id -> $boot_id) but uptime is ${uptime_s}s -- SUSPICIOUS, likely not a real reboot"\n            else\n                echo "[$d] boot_id changed ($last_fixed_boot_id -> $boot_id), uptime ${uptime_s:-unknown}s -- looks like a genuine reboot"\n            fi\n        fi\n\n        if [ "$respect_cooldown" = "1" ]; then\n            attempt_file="$HEADTRACK_STATE_DIR/attempts_$safe_name"\n            if [ -f "$attempt_file" ]; then\n                last_attempt=$(cat "$attempt_file" 2>/dev/null || echo 0)\n                now=$(date +%s)\n                elapsed=$((now - last_attempt))\n                if [ "$elapsed" -lt "$COOLDOWN_SECONDS" ]; then\n                    cooldown_skipped_count=$((cooldown_skipped_count + 1))\n                    continue\n                fi\n            fi\n            date +%s > "$attempt_file"\n        fi\n\n        echo "$d\t$tid\t$boot_id" >> "$fix_map_file"\n    done < "$detect_map_file"\n    rm -f "$detect_map_file"\nfi\nrm -rf "$scratch_detect"\n\nif [ ! -s "$fix_map_file" ]; then\n    echo "No devices need the headtracking fix this boot."\n    rm -f "$fix_map_file" "$transport_map_file"\nelse\n    fix_count=$(wc -l < "$fix_map_file")\n    log_file="$HEADTRACK_STATE_DIR/batch_fix_$(date +%Y%m%d_%H%M%S).log"\n    summary_file=$(mktemp)\n    echo "Applying headtracking fix to $fix_count device(s) now (log: $log_file)..."\n\n    {\n        scratch=$(mktemp -d)\n        pending_file="$fix_map_file"\n        max_attempts=3\n        attempt=1\n        wake_bursts=6        # matches wakeAll.sh\'s repeated-attempt cadence\n        wake_burst_gap=0.25\n\n        while [ -s "$pending_file" ] && [ "$attempt" -le "$max_attempts" ]; do\n            count=$(wc -l < "$pending_file")\n            echo "$(date): attempt $attempt/$max_attempts -- SLEEP -> $count device(s)"\n            while IFS=$\'\\t\' read -r d tid boot_id; do\n                safe_name=$(echo "$d" | tr -c \'a-zA-Z0-9\' \'_\')\n                ( exec 9>&- 2>/dev/null; timeout 10 adb -t "$tid" shell input keyevent 223 > /dev/null 2>&1 \\\n                    && echo ok > "$scratch/$safe_name.sleep" \\\n                    || echo fail > "$scratch/$safe_name.sleep" ) &\n            done < "$pending_file"\n            wait\n\n            if [ "$VISUAL_CHECK" = "1" ]; then\n                echo "$(date): waiting ${TABLET_CHECK_DELAY}s -- check the tablet now to confirm they went to sleep"\n                sleep "$TABLET_CHECK_DELAY"\n            fi\n\n            echo "$(date): WAKE -> $count device(s) ($wake_bursts rapid attempts each)"\n            while IFS=$\'\\t\' read -r d tid boot_id; do\n                safe_name=$(echo "$d" | tr -c \'a-zA-Z0-9\' \'_\')\n                (\n                    exec 9>&- 2>/dev/null\n                    result=fail\n                    for b in $(seq 1 "$wake_bursts"); do\n                        timeout 10 adb -t "$tid" shell input keyevent 224 > /dev/null 2>&1 && result=ok\n                        sleep "$wake_burst_gap"\n                    done\n                    echo "$result" > "$scratch/$safe_name.wake"\n                ) &\n            done < "$pending_file"\n            wait\n\n            echo "$(date): confirming each device came back reachable..."\n            while IFS=$\'\\t\' read -r d tid boot_id; do\n                safe_name=$(echo "$d" | tr -c \'a-zA-Z0-9\' \'_\')\n                ( exec 9>&- 2>/dev/null; timeout 10 adb -t "$tid" get-state 2>/dev/null | grep -qx device \\\n                    && echo ok > "$scratch/$safe_name.state" \\\n                    || echo fail > "$scratch/$safe_name.state" ) &\n            done < "$pending_file"\n            wait\n\n            next_pending=$(mktemp)\n            while IFS=$\'\\t\' read -r d tid boot_id; do\n                safe_name=$(echo "$d" | tr -c \'a-zA-Z0-9\' \'_\')\n                sleep_r=$(cat "$scratch/$safe_name.sleep" 2>/dev/null)\n                wake_r=$(cat "$scratch/$safe_name.wake" 2>/dev/null)\n                state_r=$(cat "$scratch/$safe_name.state" 2>/dev/null)\n                if [ "$sleep_r" = "ok" ] && [ "$wake_r" = "ok" ] && [ "$state_r" = "ok" ]; then\n                    echo "$boot_id" > "$HEADTRACK_STATE_DIR/$safe_name"\n                    rm -f "$HEADTRACK_STATE_DIR/attempts_$safe_name"\n                    echo "[$d] confirmed fixed"\n                else\n                    echo "[$d] NOT confirmed on attempt $attempt (sleep=$sleep_r wake=$wake_r reachable=$state_r)"\n                    echo "$d\t$tid\t$boot_id" >> "$next_pending"\n                fi\n            done < "$pending_file"\n\n            [ "$pending_file" != "$fix_map_file" ] && rm -f "$pending_file"\n            pending_file="$next_pending"\n            attempt=$((attempt + 1))\n        done\n\n        if [ -s "$pending_file" ]; then\n            failed_count=$(wc -l < "$pending_file")\n            echo ""\n            echo "=================================================================="\n            echo "HEADTRACKING FIX FAILED after $max_attempts attempts on:"\n            while IFS=$\'\\t\' read -r d tid boot_id; do\n                echo "    $d"\n            done < "$pending_file"\n            echo "These headsets need manual attention -- check the connection or"\n            echo "sleep/wake them by hand and re-run this script."\n            echo "=================================================================="\n        else\n            failed_count=0\n            echo "$(date): headtracking fix confirmed on all $fix_count device(s)"\n        fi\n        echo "$(( fix_count - failed_count )) $failed_count" > "$summary_file"\n\n        rm -f "$fix_map_file" "$pending_file" "$transport_map_file"\n        rm -rf "$scratch"\n    } 2>&1 | tee -a "$log_file"\n\n    read -r confirmed_this_run failed_this_run < "$summary_file"\n    rm -f "$summary_file"\nfi\n\n# --- final operator report ---\ntotal_fixed=$(( already_fixed_count + confirmed_this_run ))\necho ""\necho "===================== SUMMARY ====================="\necho "Connected & stable:              $final_count"\necho "Already fixed earlier this boot: $already_fixed_count"\necho "Fixed & confirmed this run:      $confirmed_this_run"\nif [ "$failed_this_run" -gt 0 ]; then\n    echo "FAILED to confirm:               $failed_this_run  <-- see failure list above"\nfi\nif [ "$no_bootid_count" -gt 0 ]; then\n    echo "Skipped (no boot_id readable):   $no_bootid_count"\nfi\nif [ "$no_tid_count" -gt 0 ]; then\n    echo "Skipped (no transport id):       $no_tid_count"\nfi\nif [ "$cooldown_skipped_count" -gt 0 ]; then\n    echo "Skipped (cooldown after recent failure): $cooldown_skipped_count"\nfi\necho "-----------------------------------------------------"\necho "TOTAL stable with fix applied:   $total_fixed / $final_count connected"\necho "====================================================="\n}\n\nrun_cycle() {\nif [ "$PURGE" = "1" ]; then\n    echo "PURGE requested -- disconnecting ALL adb connections and ignoring known_ips.txt for this run"\n    timeout 10 adb disconnect\n    sleep 0.5\nfi\n\n# --- what\'s already connected right now? leave the healthy ones alone ---\ndevice_lines=$(timeout 10 adb devices | tail -n +2)\nconnected_good=$(echo "$device_lines" | awk \'$2=="device" {print $1}\')\nconnected_broken=$(echo "$device_lines" | awk \'$2!="" && $2!="device" {print $1}\')\n\ngood_count=$(echo -n "$connected_good" | grep -c . || true)\necho "already stable, left untouched: $good_count device(s)"\n\n# Only clear connections that are genuinely stuck (offline/unauthorized) --\n# never a full `adb disconnect`, unless --purge already did that above.\nfor d in $connected_broken; do\n    state=$(echo "$device_lines" | awk -v d="$d" \'$1==d{print $2}\')\n    echo "clearing stuck connection: $d ($state)"\n    timeout 10 adb disconnect "$d" > /dev/null 2>&1\ndone\n\n# Remember every currently-good connection for future targeted runs\n# (even during --purge -- no reason not to keep the record accurate).\nfor d in $connected_good; do\n    grep -qxF "$d" "$KNOWN_IPS" || echo "$d" >> "$KNOWN_IPS"\ndone\n\n# --- figure out who we still need to (re)connect ---\ntargets=""\nskipped_other_subnet=0\nif [ "$PURGE" != "1" ]; then\n    while IFS= read -r known; do\n        [ -z "$known" ] && continue\n        # known_ips.txt accumulates every address ever seen across this\n        # deployment\'s whole history -- different venues, DHCP churn,\n        # subnet changes -- and is never pruned. An entry that doesn\'t\n        # match the CURRENT subnet prefix can never succeed while on this\n        # (static) router, so carrying it forward as a target is always\n        # futile -- it just inflates the attempt count with addresses that\n        # are guaranteed to fail. Skip it here rather than deleting it from\n        # the file, in case the prefix ever changes back.\n        case "$known" in\n            "$SUBNET_PREFIX".*) : ;;\n            *) skipped_other_subnet=$((skipped_other_subnet + 1)); continue ;;\n        esac\n        if ! echo "$connected_good" | grep -qxF "$known"; then\n            targets="$targets $known"\n        fi\n    done < "$KNOWN_IPS"\n    if [ "$skipped_other_subnet" -gt 0 ]; then\n        echo "skipped $skipped_other_subnet known IP(s) from a different subnet than $SUBNET_PREFIX.* -- can\'t work with the current router, left untouched in known_ips.txt"\n    fi\nfi\n\nif [ "$FULL_SCAN" = "1" ] || [ ! -s "$KNOWN_IPS" ]; then\n    if [ "$PURGE" != "1" ]; then\n        echo "full subnet scan enabled (first run, or --full-scan requested)"\n    fi\n    for i in $(seq 0 255); do\n        candidate="$SUBNET_PREFIX.$i:$PORT"\n        echo "$connected_good" | grep -qxF "$candidate" && continue\n        echo " $targets " | grep -q " $candidate " && continue\n        targets="$targets $candidate"\n    done\nfi\n\ntargets=$(echo "$targets" | xargs -n1 echo | sort -u)  # dedupe, one per line\n\nif [ -z "$targets" ]; then\n    echo "nothing to (re)connect -- all known headsets already stable."\nelse\n    target_count=$(echo -n "$targets" | grep -c .)\n    echo "attempting to (re)connect $target_count target(s), up to $CONNECT_CONCURRENCY at a time..."\n    echo "$targets" | xargs -P "$CONNECT_CONCURRENCY" -I{} bash -c \\\n        \'exec 9>&- 2>/dev/null; timeout "$1" adb connect "$2"\' _ "$CONNECT_TIMEOUT" {} > /dev/null 2>&1\nfi\n\n# --- re-check final state and update the known-IPs file ---\ndevice_lines=$(timeout 10 adb devices | tail -n +2)\nconnected_good=$(echo "$device_lines" | awk \'$2=="device" {print $1}\')\nfor d in $connected_good; do\n    grep -qxF "$d" "$KNOWN_IPS" || echo "$d" >> "$KNOWN_IPS"\ndone\nfinal_count=$(echo -n "$connected_good" | grep -c . || true)\necho "connect phase finished: $final_count device(s) now in \'device\' state."\n\n# --- build a serial -> transport_id map. Commands are sent by transport id\n# (matching your proven sleepAll.sh/wakeAll.sh), not by serial. ---\nbuild_transport_map\n\n# --- WiFi never-sleep: the actual fix for headsets dropping off wireless\n# ADB while asleep. By default Android can power down/throttle the WiFi\n# radio once idle, which is what silently breaks the adb connection during\n# sleep -- these settings tell it never to do that regardless of screen\n# state. Cheap and idempotent, applied to every connected device every run.\n# (Standard through Android 8, deprecated on later stock Android -- Go\'s\n# build is an older fork, so confirm this actually helps on your hardware\n# rather than assuming it does.)\necho "applying WiFi never-sleep policy to $final_count device(s)..."\nfor d in $connected_good; do\n    tid=$(get_tid "$d")\n    [ -z "$tid" ] && continue\n    ( exec 9>&- 2>/dev/null\n      timeout 10 adb -t "$tid" shell settings put global wifi_sleep_policy 2 > /dev/null 2>&1\n      timeout 10 adb -t "$tid" shell settings put global wifi_suspend_optimizations_enabled 0 > /dev/null 2>&1 ) &\ndone\n# Deliberately NOT waiting here -- this was already dispatched in parallel\n# across all devices, but the script still blocked until every one of them\n# finished (or hit its own 10s timeout) before moving on. These are\n# idempotent settings pushes, not required for connectivity itself, so\n# there\'s no real reason the fix-detection phase below needs to wait for\n# them -- let them keep running in the background while the script\n# proceeds. In practice the fix-application phase takes longer anyway\n# (especially now that boot_id detection is parallelized too -- see\n# below), so these naturally finish well before the script\'s own exit;\n# they\'re also in the same process group as everything else this app\n# launches, so even a genuinely slow straggler gets cleaned up along with\n# everything else if the operator stops the watchdog or closes the app.\n\n# Only the actual fix-application (sleep/wake/confirm) below needs\n# exclusive access against the watchdog -- that\'s the only step that\n# manipulates device power state in a way two concurrent processes could\n# genuinely conflict on. Everything above (connect/reconnect/WiFi policy)\n# never touches what the watchdog works with -- it only ever checks/fixes\n# devices that are ALREADY connected and stable, while reconnecting is\n# entirely about addresses that AREN\'T currently connected -- so none of\n# that needed to wait on the watchdog at all.\nMANUAL_LOCK_WAIT_MAX=30\nwaited=0\ngot_lock=0\nif acquire_lock; then\n    got_lock=1\nelse\n    echo "Waiting up to ${MANUAL_LOCK_WAIT_MAX}s for exclusive access to apply the headtracking fix (the watchdog may be mid-cycle)..."\n    while [ "$waited" -lt "$MANUAL_LOCK_WAIT_MAX" ]; do\n        sleep 2\n        waited=$((waited + 2))\n        if acquire_lock; then\n            got_lock=1\n            echo "Got it after ${waited}s -- continuing."\n            break\n        fi\n    done\nfi\nif [ "$got_lock" = "1" ]; then\n    apply_headtracking_fix\n    release_lock\nelse\n    echo "Could not get exclusive access to apply the headtracking fix after ${MANUAL_LOCK_WAIT_MAX}s -- skipping"\n    echo "the fix this run. Everything else above (connect/reconnect/WiFi policy) still completed normally."\n    echo "If this persists well beyond a normal watchdog cycle, it may be genuinely stuck -- check"\n    echo "${LOCK_FILE}.pid for the recorded holder PID."\nfi\n}\n\nwatchdog_cycle() {\n    connected_good=$(timeout 10 adb devices | tail -n +2 | awk \'$2=="device" {print $1}\')\n    final_count=$(echo -n "$connected_good" | grep -c . || true)\n\n    if [ -z "$connected_good" ]; then\n        echo "$(date): no headsets currently connected -- nothing to check"\n        return\n    fi\n\n    echo "$(date): $final_count headset(s) connected -- checking headtracking fix status"\n    build_transport_map\n    apply_headtracking_fix 1\n}\n\n# --- dispatch: single run, watchdog daemon, or nothing (args error) ---\nif [ "$WATCHDOG" = "1" ]; then\n    echo "Headtracking watchdog: waiting for at least one headset to connect..."\n    while true; do\n        if ! parent_alive; then\n            echo "Parent process (PID $PARENT_PID) is gone -- exiting before ever finding a device."\n            exit 0\n        fi\n        count=$(timeout 10 adb devices | tail -n +2 | awk \'$2=="device"\' | grep -c . || true)\n        [ "$count" -gt 0 ] && break\n        sleep 3\n    done\n    echo "Headtracking watchdog: headset detected -- checking every ${WATCHDOG_INTERVAL}s until stopped."\n    echo "This only checks/fixes whatever\'s currently connected -- it does NOT reconnect or"\n    echo "scan for headsets. Run a normal Connect (or the full connect+fix cycle) separately"\n    echo "for that; this just makes sure nothing quietly loses the fix from a reboot in between."\n    cycle_num=1\n    while true; do\n        if ! parent_alive; then\n            echo "Parent process (PID $PARENT_PID) is gone -- watchdog exiting."\n            exit 0\n        fi\n        echo ""\n        echo "########## watchdog cycle $cycle_num -- $(date) ##########"\n        if acquire_lock; then\n            watchdog_cycle\n            release_lock\n        else\n            echo "$(date): a manual massConnect.sh operation is in progress -- skipping this cycle"\n        fi\n        cycle_num=$((cycle_num + 1))\n        if ! interruptible_sleep "$WATCHDOG_INTERVAL"; then\n            echo "Parent process (PID $PARENT_PID) is gone -- watchdog exiting."\n            exit 0\n        fi\n    done\nelse\n    # No lock needed here anymore -- run_cycle acquires it internally,\n    # scoped to just the fix-application step at the end, since that\'s the\n    # only part that can genuinely conflict with a concurrent watchdog\n    # cycle. Connect/reconnect/WiFi-policy always run immediately.\n    run_cycle\nfi\n',
    'sleepAll.sh': '#!/bin/bash\n# Usage: sleepAll.sh [device_serial]\n# device_serial is optional -- if omitted, applies to ALL connected headsets.\n\n# Send sleep signal to all currently connected headsets, or just one.\n\ntarget_device="$1"\nif [ -n "$target_device" ]; then\n    devices="$target_device"\nelse\n    devices=$(adb devices | awk \'NR>1 && $2=="device" {print $1}\')\nfi\nfor d in $devices; do\n    timeout 20 adb -s "$d" shell input keyevent 223 &\ndone\nwait\n',
    'wakeAll.sh': '#!/bin/bash\n# Usage: wakeAll.sh [device_serial]\n# device_serial is optional -- if omitted, applies to ALL connected headsets.\n#\n# for y in {1..9}; do\n#     for x in {1..999}; do\n#         adb -t $x shell input keyevent 224 && exit 0 &\n#     done\n#     sleep 0.25\n# done\n\ntarget_device="$1"\nif [ -n "$target_device" ]; then\n    devices="$target_device"\nelse\n    devices=$(adb devices | awk \'NR>1 && $2=="device" {print $1}\')\nfi\nfor d in $devices; do\n    timeout 20 adb -s "$d" shell input keyevent 224 &\ndone\nwait\n',
    'stayAwake.sh': '#!/bin/bash\n# Usage: stayAwake.sh [--parent-pid PID]\n# If --parent-pid is given, this exits on its own as soon as that process is\n# no longer running -- hardens against an orphaned watchdog outliving\n# whatever launched it. Safe to omit for standalone/manual use.\n\n# LEGACY VERSION\n#\n# while true; do\n#     for x in {1..999}; do\n#         adb -t $x shell input keyevent 224 && exit 0 &\n#         sleep 0.01\n#     done\n# done\n\nPARENT_PID=""\nif [ "$1" = "--parent-pid" ]; then\n    PARENT_PID="$2"\nfi\nparent_alive() {\n    [ -z "$PARENT_PID" ] && return 0\n    kill -0 "$PARENT_PID" 2>/dev/null\n}\n\n# Sleeps in 1s chunks, checking parent liveness between each, so this\n# notices a dead parent within ~1s instead of waiting out the full 5s wake-\n# pulse interval first -- keeps the wake-pulse cadence itself unchanged.\ninterruptible_sleep() {\n    local total="$1" elapsed=0\n    while [ "$elapsed" -lt "$total" ]; do\n        parent_alive || return 1\n        sleep 1\n        elapsed=$((elapsed + 1))\n    done\n    return 0\n}\n\nwhile true; do\n    if ! parent_alive; then\n        echo "Parent process (PID $PARENT_PID) is gone -- stayAwake exiting."\n        exit 0\n    fi\n\n    devices=$(adb devices | awk \'NR>1 && $2=="device" {print $1}\')\n\n    for d in $devices; do\n        timeout 5 adb -s "$d" shell input keyevent 224 &\n    done\n    if ! interruptible_sleep 5; then\n        echo "Parent process (PID $PARENT_PID) is gone -- stayAwake exiting."\n        exit 0\n    fi\ndone\n',
    'popupWatchdog.sh': '#!/bin/bash\n# Usage: popupWatchdog.sh --package <package.name> [--interval SECONDS] [--parent-pid PID]\n#\n# Periodically checks each connected headset\'s currently-focused window. If\n# it doesn\'t match the expected package, sends the Android HOME keyevent\n# (keycode 3) -- the same input scrcpy\'s middle-click sends by default,\n# which resolves both an overheat warning and an app-crash/ANR dialog by\n# hand. This automates that check so it doesn\'t depend on someone watching\n# every batch-preview tile.\n#\n# DETECTION CAVEAT: this checks `dumpsys window windows` for the expected\n# package name in the focused-window/focused-app line -- a standard Android\n# debugging technique, but NOT verified against this specific overheat-\n# warning/crash-dialog behavior on this hardware. Before relying on this\n# unattended, deliberately trigger one of these popups on a single headset\n# and confirm this script\'s log shows it detecting and recovering -- if the\n# popup is some other kind of overlay that doesn\'t change window focus, this\n# won\'t catch it, and that\'s worth knowing before trusting it fleet-wide.\n#\n# Rate-limited per device (COOLDOWN_SECONDS) so a headset stuck in a genuine\n# crash loop gets HOME pressed periodically rather than hammered constantly\n# -- if a device needs repeated recovery, that\'s worth investigating by\n# hand rather than fighting it in a tight loop.\n\nPACKAGE=""\nPARENT_PID=""\nINTERVAL=10\nCOOLDOWN_SECONDS=30\n\nwhile [ $# -gt 0 ]; do\n    case "$1" in\n        --package) PACKAGE="$2"; shift 2 ;;\n        --parent-pid) PARENT_PID="$2"; shift 2 ;;\n        --interval) INTERVAL="$2"; shift 2 ;;\n        *) shift ;;\n    esac\ndone\n\nif [ -z "$PACKAGE" ]; then\n    echo "popupWatchdog: --package is required" >&2\n    exit 1\nfi\n\nparent_alive() {\n    [ -z "$PARENT_PID" ] && return 0\n    kill -0 "$PARENT_PID" 2>/dev/null\n}\n\ninterruptible_sleep() {\n    local total="$1" elapsed=0\n    while [ "$elapsed" -lt "$total" ]; do\n        parent_alive || return 1\n        sleep 1\n        elapsed=$((elapsed + 1))\n    done\n    return 0\n}\n\nSTATE_DIR="$HOME/.cxvr_popup_watchdog"\nmkdir -p "$STATE_DIR"\n\ncheck_and_recover() {\n    local d="$1"\n\n    local focus\n    focus=$(timeout 10 adb -s "$d" shell dumpsys window windows 2>/dev/null \\\n            | grep -E "mCurrentFocus|mFocusedApp")\n\n    if [ -z "$focus" ]; then\n        # couldn\'t determine focus this round (device slow/unreachable) --\n        # don\'t act on missing information, just skip until next cycle\n        return\n    fi\n\n    if echo "$focus" | grep -q "$PACKAGE"; then\n        return   # expected app is in front -- nothing to do\n    fi\n\n    local safe_name attempt_file last_attempt now elapsed\n    safe_name=$(echo "$d" | tr -c \'a-zA-Z0-9\' \'_\')\n    attempt_file="$STATE_DIR/attempts_$safe_name"\n    if [ -f "$attempt_file" ]; then\n        last_attempt=$(cat "$attempt_file" 2>/dev/null || echo 0)\n        now=$(date +%s)\n        elapsed=$((now - last_attempt))\n        if [ "$elapsed" -lt "$COOLDOWN_SECONDS" ]; then\n            return\n        fi\n    fi\n    date +%s > "$attempt_file"\n\n    echo "[$d] expected app not in foreground -- sending HOME to recover (focus: $(echo "$focus" | head -1 | xargs))"\n    timeout 10 adb -s "$d" shell input keyevent 3 > /dev/null 2>&1\n}\n\nwhile true; do\n    if ! parent_alive; then\n        echo "Parent process (PID $PARENT_PID) is gone -- popupWatchdog exiting."\n        exit 0\n    fi\n\n    devices=$(adb devices | awk \'NR>1 && $2=="device" {print $1}\')\n    for d in $devices; do\n        check_and_recover "$d" &\n    done\n    wait\n\n    if ! interruptible_sleep "$INTERVAL"; then\n        echo "Parent process (PID $PARENT_PID) is gone -- popupWatchdog exiting."\n        exit 0\n    fi\ndone\n',
    'screenRefresh.sh': '#!/bin/bash\n# Usage: screenRefresh.sh [device_serial]\n# device_serial is optional -- if omitted, applies to ALL connected headsets.\n#\n# for x in {0..999}; do\n#     adb -t $x shell input keyevent 223 && sleep 1 && adb -t $x shell input keyevent 224 && exit 0 &\n# done\n# sleep 5\n# pkill -P $$\n# echo "Finished."\n# exit 0\n\ntarget_device="$1"\nif [ -n "$target_device" ]; then\n    devices="$target_device"\nelse\n    devices=$(adb devices | awk \'NR>1 && $2=="device" {print $1}\')\nfi\nfor y in {1..16}; do\n    for d in $devices; do\n        timeout 15 adb -s "$d" shell input keyevent 223 &\n    done\ndone\nwait\nfor y in {1..5}; do\n    for d in $devices; do\n        timeout 15 adb -s "$d" shell input keyevent 224 &\n    done\ndone\n',
    'volumeNormalize.sh': '#!/bin/bash\n# Three operations, all built on the same proven primitives (keyevent 24 =\n# up, 25 = down):\n#\n#   volumeNormalize.sh <stages-down> [device_serial]\n#     LEGACY RELATIVE: max volume, then reduce by N stages, blind (no\n#     verification). Kept for direct terminal use; the GUI no longer calls\n#     this for anything.\n#\n#   volumeNormalize.sh --set <level|max> [device_serial]\n#     CLOSED-LOOP ABSOLUTE: reads each device\'s actual current volume,\n#     computes exactly how many up/down presses it individually needs,\n#     applies just that many, then re-reads and repeats -- up to 5 rounds --\n#     until every device is confirmed at the target or the attempts run out.\n#     This exists because blind command counts (the old floor-then-raise\n#     approach) can\'t detect or correct a dropped keyevent, which is a real,\n#     observed failure mode over wireless ADB -- headsets would end up at\n#     different actual volumes despite receiving "the same" command. Closed-\n#     loop correction fixes that by reacting to what\'s actually measured.\n#     Pass the literal word "max" instead of a number to target each\n#     device\'s own reported ceiling (from dumpsys audio\'s "Max:" line)\n#     rather than a fixed assumed number -- avoids ever chasing a target\n#     above what a given device can actually reach.\n#\n#   volumeNormalize.sh --check [device_serial]\n#     Read-only: best-effort report of each device\'s current music volume,\n#     parsed from `dumpsys audio` (STREAM_MUSIC\'s "Current:" line) rather\n#     than `settings get system volume_music`, which doesn\'t work reliably\n#     on this Android build.\n#\n# device_serial is optional in all modes -- if omitted, applies to ALL\n# connected headsets.\n\nmode="$1"\nMAX_SET_ATTEMPTS=5\nVOLUME_CONCURRENCY=20   # max simultaneous keyevent sends across the whole fleet\n                        # during a --set adjustment. Same throttling philosophy as\n                        # massConnect.sh\'s CONNECT_CONCURRENCY -- unbounded parallel\n                        # adb commands across a large fleet is what destabilized the\n                        # adb server in the past, so this caps it at a value already\n                        # proven stable elsewhere in this toolset rather than guessing\n                        # higher without evidence.\n\n# Reads ONE device\'s current STREAM_MUSIC state in a single dumpsys call.\n# Prints "CURRENT MAX" (space-separated) to stdout, either field blank if\n# unreadable. The "Current:" line looks like:\n#   Current: 2 (speaker): 11, 4 (headset): 10, ...\n# numbers alternate device-index, value, device-index, value... so the 2nd\n# number overall is the first reported volume level.\nread_volume_state() {\n    local d="$1" raw cur mx\n    raw=$(timeout 10 adb -s "$d" shell "dumpsys audio 2>/dev/null | grep -A 5 \'\\- STREAM_MUSIC:\'" 2>/dev/null)\n    cur=$(echo "$raw" | grep \'Current:\' | head -1 | grep -oE \'[0-9]+\' | sed -n \'2p\')\n    mx=$(echo "$raw" | grep -m1 \'Max:\' | grep -oE \'[0-9]+\' | head -1)\n    echo "$cur $mx"\n}\n\nif [ "$mode" = "--check" ]; then\n    target_device="$2"\nelif [ "$mode" = "--set" ]; then\n    level_arg="$2"\n    target_device="$3"\n    if [ -z "$level_arg" ]; then\n        read -p "Enter target volume level (0-15, or \'max\'): " level_arg\n    fi\n    if [ "$level_arg" = "max" ]; then\n        target_is_max=1\n    else\n        target_is_max=0\n        if ! [[ "$level_arg" =~ ^[0-9]+$ ]] || [ "$level_arg" -lt 0 ] || [ "$level_arg" -gt 15 ]; then\n            echo "Invalid input. Level must be a whole number from 0 to 15, or \'max\'."\n            exit 1\n        fi\n    fi\nelse\n    stages="$1"\n    target_device="$2"\n    if [ -z "$stages" ]; then\n        read -p "Enter number of volume-down stages: " stages\n    fi\n    if ! [[ "$stages" =~ ^[0-9]+$ ]] || [ "$stages" -lt 0 ] || [ "$stages" -gt 15 ]; then\n        echo "Invalid input. Stages must be a whole number from 0 to 15."\n        exit 1\n    fi\nfi\n\nif [ -n "$target_device" ]; then\n    devices="$target_device"\n    echo "Targeting single device: $target_device"\nelse\n    devices=$(adb devices | awk \'NR>1 && $2=="device" {print $1}\')\n    echo "Targeting all connected devices."\nfi\n\nif [ -z "$devices" ]; then\n    echo "No target devices found."\n    exit 1\nfi\n\necho "--- current volume (best effort -- may be unsupported on this build) ---"\nfor d in $devices; do\n    read -r vol _ <<< "$(read_volume_state "$d")"\n    if [ -n "$vol" ]; then\n        echo "  $d: volume=$vol"\n    else\n        echo "  $d: (could not read -- not supported on this build)"\n    fi\ndone\n\nif [ "$mode" = "--check" ]; then\n    exit 0\nfi\n\nif [ "$mode" = "--set" ]; then\n    pending="$devices"\n    attempt=1\n\n    while [ -n "$(echo "$pending" | xargs)" ] && [ "$attempt" -le "$MAX_SET_ATTEMPTS" ]; do\n        echo ""\n        echo "--- set attempt $attempt/$MAX_SET_ATTEMPTS ---"\n        scratch=$(mktemp -d)\n\n        for d in $pending; do\n            safe=$(echo "$d" | tr -c \'a-zA-Z0-9\' \'_\')\n            ( read_volume_state "$d" > "$scratch/$safe.state" ) &\n        done\n        wait\n\n        # Build a flat list of individual (device, direction) press jobs\n        # across ALL pending devices first -- no adb calls yet, just\n        # arithmetic against the readings we already have -- then dispatch\n        # the whole batch through one throttled parallel pipeline. This is\n        # what actually makes the fleet-wide adjustment run concurrently\n        # instead of finishing one headset before starting the next: a\n        # single device needing many presses no longer blocks every other\n        # device from starting. VOLUME_CONCURRENCY caps how many individual\n        # keyevent sends are in flight at once (same throttling philosophy\n        # as massConnect.sh\'s CONNECT_CONCURRENCY, chosen for the same\n        # reason: unbounded parallelism across a large fleet is what\n        # destabilized the adb server in the past).\n        job_list=$(mktemp)\n        still_pending=""\n        for d in $pending; do\n            safe=$(echo "$d" | tr -c \'a-zA-Z0-9\' \'_\')\n            read -r current reported_max < "$scratch/$safe.state" 2>/dev/null\n\n            if [ "$target_is_max" = "1" ]; then\n                this_target="${reported_max:-15}"\n            else\n                this_target="$level_arg"\n            fi\n\n            if [ -z "$current" ]; then\n                echo "[$d] could not read current volume this round -- will retry"\n                still_pending="$still_pending $d"\n                continue\n            fi\n            if [ "$current" = "$this_target" ]; then\n                echo "[$d] already at target ($this_target)"\n                continue\n            fi\n\n            delta=$((this_target - current))\n            if [ "$delta" -gt 0 ]; then\n                echo "[$d] at $current, target $this_target -- will press UP x$delta"\n                for i in $(seq 1 "$delta"); do echo "$d\t24" >> "$job_list"; done\n            else\n                abs_delta=$((-delta))\n                echo "[$d] at $current, target $this_target -- will press DOWN x$abs_delta"\n                for i in $(seq 1 "$abs_delta"); do echo "$d\t25" >> "$job_list"; done\n            fi\n            still_pending="$still_pending $d"\n        done\n\n        if [ -s "$job_list" ]; then\n            job_count=$(wc -l < "$job_list")\n            echo "dispatching $job_count keyevent(s) across the fleet, up to $VOLUME_CONCURRENCY at a time..."\n            xargs -P "$VOLUME_CONCURRENCY" -L 1 -a "$job_list" bash -c \\\n                \'timeout 15 adb -s "$1" shell input keyevent "$2"\' _\n        fi\n        rm -f "$job_list"\n        rm -rf "$scratch"\n\n        pending=$(echo "$still_pending" | xargs -n1 echo 2>/dev/null | sort -u | xargs)\n        attempt=$((attempt + 1))\n    done\n\n\n    echo ""\n    echo "===================== VOLUME SET SUMMARY ====================="\n    confirmed=0\n    total=0\n    for d in $devices; do\n        total=$((total + 1))\n        read -r cur mx <<< "$(read_volume_state "$d")"\n        if [ "$target_is_max" = "1" ]; then\n            this_target="${mx:-15}"\n        else\n            this_target="$level_arg"\n        fi\n        if [ "$cur" = "$this_target" ]; then\n            echo "[$d] CONFIRMED at $this_target"\n            confirmed=$((confirmed + 1))\n        else\n            echo "[$d] NOT CONFIRMED -- reads ${cur:-unknown}, target was $this_target"\n        fi\n    done\n    echo "-----------------------------------------------------------------"\n    echo "$confirmed / $total device(s) confirmed at target"\n    echo "==================================================================="\nelse\n    echo "Maxing volume on target device(s)..."\n    for y in {1..15}; do\n        for d in $devices; do\n            timeout 15 adb -s "$d" shell input keyevent 24 &\n        done\n    done\n    wait\n\n    echo "Reducing by $stages stage(s)..."\n    for y in $(seq 1 "$stages"); do\n        for d in $devices; do\n            timeout 15 adb -s "$d" shell input keyevent 25 &\n        done\n    done\n    wait\n\n    echo "Volume set: max minus $stages stage(s)."\nfi\n',
    'rebootAll.sh': '#!/bin/bash\n# Usage: rebootAll.sh [device_serial]\n# device_serial is optional -- if omitted, applies to ALL connected headsets.\n# Matches the optional-target convention already used by sleepAll.sh,\n# wakeAll.sh and screenRefresh.sh.\n# for x in {1..999}; do\n#     adb -t $x shell reboot && exit 0 &\n# done\n# wait\n# echo "Finished."\n# exit 0\n\ntarget_device="$1"\nif [ -n "$target_device" ]; then\n    devices="$target_device"\nelse\n    devices=$(adb devices | awk \'NR>1 && $2=="device" {print $1}\')\nfi\nfor d in $devices; do\n    timeout 20 adb -s "$d" shell reboot &\ndone\nwait\n',
    'powerOff.sh': '#!/bin/bash\n# Usage: powerOff.sh [device_serial]\n# device_serial is optional -- if omitted, applies to ALL connected headsets.\n# Matches the optional-target convention already used by sleepAll.sh,\n# wakeAll.sh and screenRefresh.sh.\n# for x in {1..999}; do\n#     adb -t $x shell reboot -p && exit 0 &\n# done\n# wait\n# echo "Finished."\n# exit 0\n\ntarget_device="$1"\nif [ -n "$target_device" ]; then\n    devices="$target_device"\nelse\n    devices=$(adb devices | awk \'NR>1 && $2=="device" {print $1}\')\nfi\nfor d in $devices; do\n    timeout 20 adb -s "$d" shell reboot -p &\ndone\nwait\n',
    'heartbeatMaintain.sh': '#!/bin/bash\n# Usage: heartbeatMaintain.sh [--parent-pid PID]\n# If --parent-pid is given, this exits on its own as soon as that process is\n# no longer running -- hardens against an orphaned watchdog outliving\n# whatever launched it. Safe to omit for standalone/manual use.\n\n# while true; do\n#     for x in {1..999}; do\n#         adb -t $x shell echo alive$x && exit 0 &\n#         sleep 0.01\n#     done\n# done\n\nPARENT_PID=""\nif [ "$1" = "--parent-pid" ]; then\n    PARENT_PID="$2"\nfi\nparent_alive() {\n    [ -z "$PARENT_PID" ] && return 0\n    kill -0 "$PARENT_PID" 2>/dev/null\n}\n\nwhile true; do\n    if ! parent_alive; then\n        echo "Parent process (PID $PARENT_PID) is gone -- heartbeat monitor exiting."\n        exit 0\n    fi\n\n    devices=$(adb devices | awk \'NR>1 && $2=="device" {print $1}\')\n    for d in $devices; do\n        timeout 20 adb -s "$d" shell echo "$d is alive" &\n        sleep 0.5\n    done\n    wait\ndone\n',
    'sync_files.py': '#!/usr/bin/env python3\n"""\nsync_files.py — Robust wireless-ADB content sync for fleets of Oculus Go headsets.\n\nDesign goals (in response to a fragile bash/adb script that re-hashed every\nfile over adb shell on every run):\n\n  1. Trust-but-verify: keep a local record of what each headset already has.\n     Unchanged content = zero adb calls, not thousands.\n  2. Self-healing: --verify forces a full remote reconciliation to catch\n     headsets that were reset/tampered with, without slowing normal runs.\n  3. Direct, space-aware overwrite: these are 32GB Oculus Go units running\n     near capacity, so files push straight to their final path rather than\n     via a temp-copy-then-rename (which would transiently need old+new+temp\n     space at once). The script tracks free space per device and skips a\n     push that wouldn\'t fit rather than starting a transfer it can\'t finish\n     and leaving a corrupted file at the real path.\n  4. Batched remote calls: mkdir/stat are batched into few shell invocations\n     instead of one round-trip per file.\n  5. Bounded concurrency + retry/reconnect: a handful of headsets in parallel,\n     with automatic `adb connect` retry if wireless ADB drops mid-run.\n  6. Power management: optionally disables the sleep timer on each headset\n     (screen_off_timeout / stayon) so a multi-hour sync or idle period between\n     showings doesn\'t let a headset fall asleep and drop off wireless ADB.\n     A separate --keepalive watchdog mode sends a periodic non-destructive\n     wake pulse and flags any headset that stops responding.\n  7. Clear summary + non-zero exit code on any failure, safe to script/cron.\n  8. Headjack-aware safety and diagnostics, reverse-engineered from a live\n     device (not documented anywhere by Headjack): the app\'s own\n     bookkeeping files (files/v3.local, manifest.tsv, pc_manifest.txt,\n     files/App/<id>.v3) are never eligible for --prune regardless of how\n     broadly --remote-target is scoped; the --package fallback defaults to\n     the actual confirmed video location (files/Video) rather than the\n     bare app data root; local .f2d files are checked for standard image\n     magic bytes (a real .f2d is a proprietary transcoded format and won\'t\n     match one, so a match means something was very likely mis-named);\n     and --check-catalog-ids cross-references local content-ID folders\n     against the app\'s own catalog to catch typos/stale folders that would\n     otherwise sync "successfully" while never actually appearing in the\n     headset\'s menu.\n\nUsage examples:\n    # Normal sync (fast path, trusts last-known-good state per headset)\n    python3 sync_files.py --content-dir ./content --package com.CulturalXchange.BibleSchool\n\n    # Force full reconciliation against every headset (e.g. weekly, or after\n    # suspecting a headset was reset / tampered with)\n    python3 sync_files.py --content-dir ./content --package com.CulturalXchange.BibleSchool --verify\n\n    # Dry run to see what WOULD happen\n    python3 sync_files.py --content-dir ./content --package com.CulturalXchange.BibleSchool --dry-run\n\n    # Reconnect a known set of headsets by IP before syncing (wireless ADB\n    # sometimes drops the device off `adb devices` entirely — this brings it\n    # back). One host:port per line in the file.\n    python3 sync_files.py ... --connect-file headsets.txt\n\n    # Run a standalone keepalive watchdog (e.g. during a long event day or\n    # overnight) that wakes each headset every 20 minutes so it never hits\n    # its sleep timeout, and logs any headset that goes unreachable.\n    python3 sync_files.py --keepalive --connect-file headsets.txt --interval 1200\n\n    # Detect and clean up stale files/v3.local entries (the app\'s own\n    # record claims a download exists but the file\'s actually missing --\n    # e.g. after cloning one headset\'s whole Android/data folder to\n    # another). Runs alongside a normal sync; add --dry-run to only report\n    # what would be cleaned without changing anything.\n    python3 sync_files.py --content-dir ./content --package com.CulturalXchange.BibleSchool --clean-stale-metadata\n\n    # Warn about local content folders that don\'t match anything in the\n    # app\'s own catalog -- catches a typo\'d or stale content-ID folder\n    # before it gets pushed for nothing (it would sync "successfully" but\n    # never actually show up in the headset\'s menu).\n    python3 sync_files.py --content-dir ./content --package com.CulturalXchange.BibleSchool --check-catalog-ids\n"""\n\nimport argparse\nimport concurrent.futures\nimport hashlib\nimport json\nimport os\nimport re\nimport shlex\nimport subprocess\nimport sys\nimport tempfile\nimport time\nfrom datetime import datetime\nfrom pathlib import Path\n\nDEFAULT_STATE_DIR = Path.home() / ".cxvr_sync"\nADB_TIMEOUT_SHORT = 15      # get-state, mkdir, stat batches\nPUSH_TIMEOUT_FLOOR = 600    # minimum per-file push timeout regardless of size (adb call overhead,\n                            # tiny files) -- this used to be the ONLY push timeout (ADB_TIMEOUT_PUSH),\n                            # a flat 600s. A real run confirmed that\'s not enough once the content\n                            # library includes a multi-GB outlier: a 7.6GB file pushing to 5 concurrent\n                            # devices hit this exact ceiling (logs showed near-identical ~600/601/602s\n                            # gaps between push start and "TIMEOUT" on every device) while still\n                            # legitimately transferring, not stalled -- the fleet\'s own diagnosed\n                            # concurrent-transfer floor (~9-10 MB/s per device once several headsets\n                            # share the measured 45-53 MB/s aggregate ceiling) needs ~800s for a file\n                            # that size, past the old flat limit. See push_timeout_for() below.\nPUSH_TIMEOUT_MIN_MBPS = 5   # deliberately pessimistic assumed floor throughput used only to size the\n                            # timeout -- well under the ~9-10 MB/s per-device floor actually measured\n                            # even at full concurrency, so a real transfer should essentially never\n                            # take this long; this is a generous ceiling to fail *by*, not an expected\n                            # rate\nPUSH_TIMEOUT_SAFETY_FACTOR = 2   # extra headroom on top of the already-pessimistic estimate above\nPUSH_STALL_CHECK_INTERVAL = 30   # how often to check the remote file\'s growing size, in seconds,\n                                  # while a push is in progress\nPUSH_STALL_TIMEOUT = 90          # if the remote file hasn\'t grown at all in this long, the push\n                                  # is almost certainly stalled (dead connection, hung adb) rather\n                                  # than legitimately slow -- kill and fail it immediately instead\n                                  # of waiting out the full size-scaled timeout above, which for a\n                                  # large file can otherwise be tens of minutes on a transfer\n                                  # that\'s actually already dead\nPUSH_POLL_INTERVAL = 5            # how often the push subprocess itself is checked for having\n                                   # already exited, independent of the stall check above\nPUSH_RETRIES = 3\nREMOTE_SIZE_TIMEOUT = 120   # full-device stat-based scan (metadata only, cheap even for many GB)\nREMOTE_HASH_TIMEOUT = 900   # full-device md5sum scan (--verify-hash) -- reads every byte on the\n                            # headset\'s own weak CPU, tens of GB can genuinely take this long\nDEVICE_RETRIES = 2          # reconnect attempts per device\nBATCH_CHUNK = 150           # files per batched shell command (mkdir/stat)\nDEFAULT_MIN_FREE_MB = 300   # safety margin kept free on /sdcard at all times\nDEFAULT_KEEPALIVE_INTERVAL = 1200   # 20 min — comfortably under a ~2h sleep timeout\nDEFAULT_SCREEN_OFF_TIMEOUT_MS = 86400000  # 24h; effectively "don\'t sleep" for an event window\n\n\n# --------------------------------------------------------------------------\n# small utilities\n# --------------------------------------------------------------------------\n\ndef now_iso():\n    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")\n\n\ndef sanitize(serial: str) -> str:\n    """Turn an adb serial like 192.168.1.42:5555 into a safe filename."""\n    return "".join(c if c.isalnum() else "_" for c in serial)\n\n\nclass Log:\n    """Thread-safe-ish console+file logger with per-device prefixing."""\n\n    def __init__(self, logfile: Path):\n        self.logfile = logfile\n        logfile.parent.mkdir(parents=True, exist_ok=True)\n        self._fh = open(logfile, "a", buffering=1)\n\n    def line(self, msg: str, device: str = None):\n        prefix = f"[{now_iso()}][CXVR]" + (f"[{device}]" if device else "")\n        out = f"{prefix} {msg}"\n        print(out, flush=True)\n        self._fh.write(out + "\\n")\n\n    def blank(self):\n        """A plain blank line (no timestamp/prefix) to visually separate sections of output --\n        used sparingly, only at natural boundaries (start of per-device work, before the\n        summary), since most of a run\'s output comes from several devices logging concurrently\n        and interleaving a blank line mid-stream wouldn\'t mean much there."""\n        print("", flush=True)\n        self._fh.write("\\n")\n\n    def close(self):\n        self._fh.close()\n\n\n# --------------------------------------------------------------------------\n# adb wrappers\n# --------------------------------------------------------------------------\n\ndef run_adb(args, timeout=ADB_TIMEOUT_SHORT):\n    try:\n        return subprocess.run(\n            ["adb"] + args, capture_output=True, text=True, timeout=timeout\n        )\n    except subprocess.TimeoutExpired:\n        return subprocess.CompletedProcess(args, 1, "", "TIMEOUT")\n\n\ndef adb_devices():\n    """Return dict serial -> state (\'device\', \'unauthorized\', \'offline\', ...)."""\n    res = run_adb(["devices"])\n    devices = {}\n    for line in res.stdout.splitlines()[1:]:\n        line = line.strip()\n        if not line:\n            continue\n        parts = line.split()\n        if len(parts) >= 2:\n            devices[parts[0]] = parts[1]\n    return devices\n\n\ndef adb_connect(host_port: str, log: Log):\n    res = run_adb(["connect", host_port], timeout=10)\n    ok = "connected" in (res.stdout or "").lower()\n    log.line(f"connect {host_port}: {res.stdout.strip() or res.stderr.strip()}")\n    return ok\n\n\ndef device_alive(serial: str) -> bool:\n    res = run_adb(["-s", serial, "get-state"], timeout=10)\n    return res.returncode == 0 and res.stdout.strip() == "device"\n\n\ndef shell(serial: str, command: str, timeout=ADB_TIMEOUT_SHORT):\n    return run_adb(["-s", serial, "shell", command], timeout=timeout)\n\n\n# --------------------------------------------------------------------------\n# local content manifest (with an on-disk hash cache so re-runs are cheap)\n# --------------------------------------------------------------------------\n\ndef md5_file(path: Path, chunk=1024 * 1024) -> str:\n    h = hashlib.md5()\n    with open(path, "rb") as f:\n        for block in iter(lambda: f.read(chunk), b""):\n            h.update(block)\n    return h.hexdigest()\n\n\n# A genuine Headjack .f2d file is a proprietary, server-generated format\n# (confirmed on a live device: `file` reports it as generic "data", not\n# "JPEG/PNG image data" -- it has its own MIME type, image/x-f2d, and its\n# own separate CDN URL distinct from the original image). It can\'t be\n# produced locally. If a .f2d file in the local content folder actually\n# starts with a standard image format\'s magic bytes, that\'s a strong sign\n# someone (or some tooling) accidentally named a raw JPEG/PNG/GIF with a\n# .f2d extension rather than using Headjack\'s real transcoded output --\n# pushing it would very likely fail to display correctly on-device, and\n# that kind of failure is hard to diagnose after the fact since sync\n# itself would report success. This only warns; it doesn\'t block the push,\n# since it can\'t be 100% certain and the operator may have a legitimate\n# .f2d obtained a different way.\n_IMAGE_MAGIC = {\n    b"\\xff\\xd8\\xff": "JPEG",\n    b"\\x89PNG\\r\\n\\x1a\\n": "PNG",\n    b"GIF87a": "GIF",\n    b"GIF89a": "GIF",\n}\n\n\ndef check_suspicious_f2d(path: Path, log: Log):\n    try:\n        with open(path, "rb") as f:\n            head = f.read(16)\n    except OSError:\n        return\n    for magic, fmt in _IMAGE_MAGIC.items():\n        if head.startswith(magic):\n            log.line(f"WARNING: {path.name} is named .f2d but starts with {fmt} magic bytes -- "\n                      f"this looks like a raw image mistakenly named .f2d, not Headjack\'s real "\n                      f"transcoded format, and will likely fail to display correctly on-device. "\n                      f"Genuine .f2d files come from Headjack\'s own CMS/CDN, not something producible "\n                      f"locally.")\n            return\n\n\ndef build_local_manifest(content_dir: Path, cache_path: Path, log: Log, scan_subdirs=None):\n    """scan_subdirs, if given (e.g. ["files/Video", "files/Media"]), restricts\n    file discovery to just those subdirectories under content_dir -- used\n    when content_dir is the app\'s own root folder (matching the on-device\n    layout) rather than a folder curated to contain only sync-worthy\n    content. Relative paths are still computed against content_dir itself\n    (not each subdir), so they come out as "files/Video/..." etc., matching\n    the real on-device paths exactly. Without scan_subdirs, behaves exactly\n    as before -- scans everything under content_dir."""\n    cache = {}\n    if cache_path.exists():\n        try:\n            cache = json.loads(cache_path.read_text())\n        except Exception:\n            cache = {}\n\n    manifest = {}\n    new_cache = {}\n    if scan_subdirs:\n        files = []\n        for sub in scan_subdirs:\n            subdir = content_dir / sub\n            if subdir.is_dir():\n                files.extend(p for p in subdir.rglob("*") if p.is_file())\n        log.line(f"scanning {len(files)} local files under {content_dir} "\n                  f"(restricted to: {\', \'.join(scan_subdirs)})")\n    else:\n        files = [p for p in content_dir.rglob("*") if p.is_file()]\n        log.line(f"scanning {len(files)} local files under {content_dir}")\n\n    for p in files:\n        rel = str(p.relative_to(content_dir)).replace(os.sep, "/")\n        if p.suffix == ".f2d":\n            check_suspicious_f2d(p, log)\n        stat = p.stat()\n        key = rel\n        cached = cache.get(key)\n        if cached and cached["mtime"] == stat.st_mtime and cached["size"] == stat.st_size:\n            md5 = cached["md5"]\n        else:\n            md5 = md5_file(p)\n        new_cache[key] = {"mtime": stat.st_mtime, "size": stat.st_size, "md5": md5}\n        manifest[rel] = {"size": stat.st_size, "md5": md5}\n\n    cache_path.parent.mkdir(parents=True, exist_ok=True)\n    cache_path.write_text(json.dumps(new_cache))\n    return manifest\n\n\n# --------------------------------------------------------------------------\n# per-device state (what we believe is already on that headset)\n# --------------------------------------------------------------------------\n\ndef load_device_state(state_dir: Path, serial: str):\n    p = state_dir / "devices" / f"{sanitize(serial)}.json"\n    if p.exists():\n        try:\n            return json.loads(p.read_text())\n        except Exception:\n            return None\n    return None\n\n\ndef save_device_state(state_dir: Path, serial: str, manifest: dict):\n    p = state_dir / "devices" / f"{sanitize(serial)}.json"\n    p.parent.mkdir(parents=True, exist_ok=True)\n    p.write_text(json.dumps({"manifest": manifest, "last_sync": now_iso()}))\n\n\ndef load_failed_pushes(state_dir: Path, serial: str) -> dict:\n    """Per-device record of pushes that failed on a previous run and haven\'t succeeded since:\n    {rel_path: {"size": bytes, "at": iso timestamp}}. Kept separate from the trusted-state\n    manifest because that one is deliberately only saved on fully clean runs, while this one\n    has to survive exactly the runs that weren\'t clean. Used to explain a later low-storage skip:\n    as far as we know, adbd deletes a partial file when a push aborts, but the headset can keep\n    that deleted file\'s space reserved (still held open on-device) until it\'s rebooted -- which\n    looks like "file missing, but free space far lower than it should be"."""\n    p = state_dir / "devices" / f"{sanitize(serial)}.failed_pushes.json"\n    if p.exists():\n        try:\n            data = json.loads(p.read_text())\n            return data if isinstance(data, dict) else {}\n        except Exception:\n            return {}\n    return {}\n\n\ndef save_failed_pushes(state_dir: Path, serial: str, record: dict):\n    p = state_dir / "devices" / f"{sanitize(serial)}.failed_pushes.json"\n    if not record:\n        if p.exists():\n            p.unlink()\n        return\n    p.parent.mkdir(parents=True, exist_ok=True)\n    p.write_text(json.dumps(record, indent=2))\n\n\n# --------------------------------------------------------------------------\n# remote reconciliation (used for --verify or when we have no trusted state)\n# --------------------------------------------------------------------------\n\ndef remote_md5_manifest(serial: str, remote_target: str, log: Log):\n    """One batched shell call: md5sum every file under remote_target (full\n    byte-for-byte content hash). Returns None (not an empty dict) if the\n    scan failed or timed out -- reading and hashing tens of GB of video on\n    a headset\'s own weak CPU can easily exceed the timeout, and treating\n    that as "device has nothing" would make every real file look missing\n    and get needlessly re-pushed. Much slower than remote_size_manifest;\n    only used when --verify-hash is explicitly requested."""\n    cmd = f"cd {shlex.quote(remote_target)} 2>/dev/null && find . -type f -exec md5sum {{}} +"\n    res = shell(serial, cmd, timeout=REMOTE_HASH_TIMEOUT)\n    if res.returncode != 0 or res.stderr == "TIMEOUT":\n        log.line(f"remote hash scan failed or timed out ({REMOTE_HASH_TIMEOUT}s) -- "\n                  f"treating as unknown, NOT as empty (a timeout here previously caused every "\n                  f"real file to look missing and get needlessly re-pushed)", serial)\n        return None\n    remote = {}\n    for line in (res.stdout or "").splitlines():\n        line = line.rstrip("\\r")\n        if not line or " " not in line:\n            continue\n        md5, path = line.split(None, 1)\n        path = path.strip()\n        if path.startswith("./"):\n            path = path[2:]\n        remote[path] = md5\n    return remote\n\n\ndef remote_size_manifest(serial: str, remote_target: str, log: Log):\n    """One batched shell call: file size (not content hash) of every file\n    under remote_target -- reads only filesystem metadata via `stat`,\n    never the file\'s actual contents, so it\'s dramatically cheaper than a\n    full md5sum scan for large video files. This is the default for full\n    remote reconciliation; --verify-hash opts into the slower, byte-exact\n    remote_md5_manifest instead. Returns None (not an empty dict) on\n    failure/timeout, for the same reason as remote_md5_manifest."""\n    cmd = f"cd {shlex.quote(remote_target)} 2>/dev/null && find . -type f -exec stat -c \'%s %n\' {{}} +"\n    res = shell(serial, cmd, timeout=REMOTE_SIZE_TIMEOUT)\n    if res.returncode != 0 or res.stderr == "TIMEOUT":\n        log.line(f"remote size scan failed or timed out ({REMOTE_SIZE_TIMEOUT}s) -- "\n                  f"treating as unknown, NOT as empty", serial)\n        return None\n    remote = {}\n    for line in (res.stdout or "").splitlines():\n        line = line.rstrip("\\r")\n        if not line or " " not in line:\n            continue\n        size_str, path = line.split(None, 1)\n        path = path.strip()\n        if path.startswith("./"):\n            path = path[2:]\n        try:\n            remote[path] = int(size_str)\n        except ValueError:\n            continue\n    return remote\n\n\n# --------------------------------------------------------------------------\n# diffing\n# --------------------------------------------------------------------------\n\n# Headjack\'s own bookkeeping files -- reverse-engineered from a live device\n# (files/v3.local: per-device download tracking; manifest.tsv/pc_manifest.txt:\n# desktop-tool-generated integrity checksums at the app data root;\n# files/App/<id>.v3: the CMS-managed content catalog). None of these are\n# ever part of what a content sync should push OR delete -- but a --prune\n# run has no way to know that on its own, since it just deletes anything\n# remote that isn\'t present locally, and none of these files live in a\n# typical local content folder. If remote_target is ever pointed somewhere\n# broad enough to include them (e.g. the app\'s data root rather than\n# specifically files/Video), an ordinary --prune could otherwise delete\n# the app\'s own catalog or download record. This check is basename/pattern\n# based rather than tied to one exact relative path, since the actual rel\n# path depends on how deep remote_target itself points.\ndef is_protected_headjack_file(rel_path: str) -> bool:\n    name = Path(rel_path).name\n    parts = Path(rel_path).parts\n    if name in ("v3.local", "manifest.tsv", "pc_manifest.txt"):\n        return True\n    if name.endswith(".v3") and "App" in parts:\n        return True\n    if ".bak" in name:   # catches .bak, .bak2, .bak.<timestamp> -- any backup of a protected file\n        return True\n    if "UnityShaderCache" in parts:   # compiled per-device against its own GPU/driver\n        return True\n    if "il2cpp" in parts:   # Unity\'s own runtime/installation metadata, not content\n        return True\n    return False\n\n\ndef diff_manifests(local: dict, remote_known: dict, compare_by: str = "md5"):\n    """Returns (to_push, to_delete, skipped_protected). compare_by selects\n    which field of the local manifest to compare against remote_known\'s\n    values -- "md5" (default, byte-exact) or "size" (much cheaper, used\n    with remote_size_manifest). skipped_protected lists any LOCAL file\n    that matched a protected Headjack bookkeeping pattern (see\n    is_protected_headjack_file) and was excluded from to_push -- these\n    are device-specific files (each headset\'s own v3.local, its own\n    Unity shader cache, etc.) that should never be pushed from one\n    device\'s content folder onto another; pushing them would overwrite\n    each target device\'s own independent state with whatever device the\n    local folder happened to be cloned from. This is deliberately loud\n    (returned for the caller to log) rather than a silent skip, since it\n    usually means --content-dir is pointed at a full device clone rather\n    than curated content -- something worth the operator noticing and\n    fixing at the source, not just working around silently on every run."""\n    to_push = []\n    skipped_protected = []\n    for rel, info in local.items():\n        if is_protected_headjack_file(rel):\n            skipped_protected.append(rel)\n            continue\n        known = remote_known.get(rel)\n        if compare_by == "size":\n            if known is None or known != info["size"]:\n                to_push.append(rel)\n        else:\n            known_md5 = known["md5"] if isinstance(known, dict) else known\n            if known_md5 != info["md5"]:\n                to_push.append(rel)\n    to_delete = [rel for rel in remote_known if rel not in local and not is_protected_headjack_file(rel)]\n    return to_push, to_delete, skipped_protected\n\n\n# --------------------------------------------------------------------------\n# batched remote operations\n# --------------------------------------------------------------------------\n\ndef batched_mkdir(serial: str, dirs, log: Log):\n    dirs = sorted(set(d for d in dirs if d and d != "."))\n    for i in range(0, len(dirs), BATCH_CHUNK):\n        chunk = dirs[i:i + BATCH_CHUNK]\n        cmd = "mkdir -p " + " ".join(shlex.quote(d) for d in chunk)\n        shell(serial, cmd, timeout=60)\n\n\ndef batched_size_check(serial: str, remote_paths, log: Log):\n    """Returns dict remote_path -> size (int) or None if missing."""\n    sizes = {}\n    paths = list(remote_paths)\n    for i in range(0, len(paths), BATCH_CHUNK):\n        chunk = paths[i:i + BATCH_CHUNK]\n        cmd = " ; ".join(\n            f"printf \'%s:\' {shlex.quote(p)}; stat -c%s {shlex.quote(p)} 2>/dev/null || echo -n MISSING; echo"\n            for p in chunk\n        )\n        res = shell(serial, cmd, timeout=90)\n        for line in (res.stdout or "").splitlines():\n            line = line.rstrip("\\r")\n            if ":" not in line:\n                continue\n            path, val = line.split(":", 1)\n            sizes[path] = None if val.strip() == "MISSING" else int(val.strip())\n    return sizes\n\n\n# --------------------------------------------------------------------------\n# free space (32GB Go units run near capacity — never start a push that\n# can\'t finish)\n# --------------------------------------------------------------------------\n\ndef get_free_bytes(serial: str, path: str = "/sdcard", log: Log = None):\n    """Best-effort free-space query. Returns bytes, or None if unparseable\n    (in which case callers should fail open rather than block all syncs)."""\n    res = shell(serial, f"df {shlex.quote(path)}", timeout=15)\n    out = (res.stdout or "") + (res.stderr or "")\n    # Match a line with three numbers followed by a percentage — robust to\n    # both standard and wrapped/busybox df layouts across toolbox versions.\n    import re\n    for m in re.finditer(r"(\\d+)\\s+(\\d+)\\s+(\\d+)\\s+\\d+%", out):\n        available_kb = int(m.group(3))\n        return available_kb * 1024\n    if log:\n        log.line(f"could not parse `df {path}` output — free-space checks disabled for this push batch", serial)\n    return None\n\n\n# --------------------------------------------------------------------------\n# push a single file directly to its final path (no temp copy — these are\n# 32GB devices running near capacity, so a temp+rename would transiently\n# need old+new+temp space at once, which is exactly what we don\'t have).\n# Space to fit the write is checked by the caller before this is invoked.\n# --------------------------------------------------------------------------\n\ndef push_timeout_for(size_bytes: int) -> int:\n    """Per-file adb push timeout, sized generously from the file\'s byte count instead of a flat\n    constant. Floors at PUSH_TIMEOUT_FLOOR (covers per-call adb overhead and small files), then for\n    anything larger assumes a deliberately pessimistic throughput floor (PUSH_TIMEOUT_MIN_MBPS) and\n    doubles that estimate (PUSH_TIMEOUT_SAFETY_FACTOR) for headroom. A real transfer completing\n    anywhere near this timeout would indicate a genuinely stalled connection worth failing on --\n    the point is not to kill a large file that\'s still legitimately in flight under concurrent\n    load, the way the old flat 600s constant did. This is a ceiling of last resort: see\n    push_one()/_push_with_stall_detection() below for the progress-based check that normally\n    catches a dead transfer long before this timeout would ever be reached."""\n    size_mb = size_bytes / 1_048_576\n    estimated = (size_mb / PUSH_TIMEOUT_MIN_MBPS) * PUSH_TIMEOUT_SAFETY_FACTOR\n    return max(PUSH_TIMEOUT_FLOOR, int(estimated))\n\n\ndef remote_file_size(serial: str, remote_path: str):\n    """Best-effort current size (bytes) of a single remote file, used only to detect a stalled\n    push already in progress -- returns None if the file doesn\'t exist yet (e.g. adb hasn\'t\n    started writing it) or the stat call itself fails, either of which is treated as "no progress\n    info this check" rather than an error, since a dead connection will simply keep returning\n    None or the same size on every subsequent check until the stall timeout catches it."""\n    res = shell(serial, f"stat -c \'%s\' {shlex.quote(remote_path)} 2>/dev/null", timeout=ADB_TIMEOUT_SHORT)\n    if res.returncode != 0 or not (res.stdout or "").strip():\n        return None\n    try:\n        return int(res.stdout.strip().splitlines()[0])\n    except ValueError:\n        return None\n\n\ndef _spawn_push(serial: str, local_path: Path, remote_path: str, stderr_file):\n    """Isolated for testing -- swap this out to drive _push_with_stall_detection with a fake\n    process instead of a real adb subprocess. stdout is discarded and stderr goes to a real file\n    (not a pipe) so a chatty progress bar can never fill a pipe buffer and block the child while\n    we\'re busy polling instead of draining it."""\n    return subprocess.Popen(["adb", "-s", serial, "push", str(local_path), remote_path],\n                             stdout=subprocess.DEVNULL, stderr=stderr_file)\n\n\ndef _push_with_stall_detection(serial: str, local_path: Path, remote_path: str, timeout: int,\n                                time_func=time.time):\n    """Runs `adb push` as a subprocess, polling the remote file\'s growing size in the background.\n    Returns (success, stalled, stderr_text). stalled is True only when THIS function killed the\n    process for lack of on-device progress (no growth for PUSH_STALL_TIMEOUT seconds) -- distinct\n    from a normal non-zero adb exit or the overall size-scaled timeout being hit, both of which\n    still apply as a fallback (a device that\'s slow to report `stat` output, or a transfer that\'s\n    genuinely progressing but each individual poll happens not to catch new bytes, is not\n    mistaken for a stall by itself; only a sustained absence of growth is). time_func is injectable\n    for testing so this never depends on real wall-clock waits."""\n    start = time_func()\n    with tempfile.TemporaryFile(mode="w+b") as err_f:\n        proc = _spawn_push(serial, local_path, remote_path, err_f)\n        last_known_size = -1\n        last_progress_time = start\n        next_stall_check = start + PUSH_STALL_CHECK_INTERVAL\n\n        while True:\n            try:\n                proc.wait(timeout=PUSH_POLL_INTERVAL)\n                err_f.seek(0)\n                return proc.returncode == 0, False, err_f.read().decode(errors="replace")\n            except subprocess.TimeoutExpired:\n                pass\n\n            now = time_func()\n            if now - start >= timeout:\n                proc.kill()\n                proc.wait()\n                err_f.seek(0)\n                return False, False, err_f.read().decode(errors="replace")\n\n            if now >= next_stall_check:\n                next_stall_check = now + PUSH_STALL_CHECK_INTERVAL\n                current_size = remote_file_size(serial, remote_path)\n                if current_size is not None and current_size > last_known_size:\n                    last_known_size = current_size\n                    last_progress_time = now\n                elif now - last_progress_time >= PUSH_STALL_TIMEOUT:\n                    proc.kill()\n                    proc.wait()\n                    return False, True, (f"no growth on {remote_path} for "\n                                          f"{PUSH_STALL_TIMEOUT}s (last known size "\n                                          f"{max(last_known_size, 0)} bytes)")\n\n\ndef push_one(serial: str, local_path: Path, remote_path: str, log: Log):\n    size_bytes = local_path.stat().st_size\n    timeout = push_timeout_for(size_bytes)\n    for attempt in range(1, PUSH_RETRIES + 1):\n        ok, stalled, stderr_text = _push_with_stall_detection(serial, local_path, remote_path, timeout)\n        if ok:\n            return True\n        if stalled:\n            log.line(f"push attempt {attempt}/{PUSH_RETRIES} STALLED for {remote_path} -- killed "\n                      f"early after no on-device growth ({stderr_text}) rather than waiting out "\n                      f"the full {timeout}s timeout", serial)\n        else:\n            log.line(f"push attempt {attempt}/{PUSH_RETRIES} failed for {remote_path} "\n                      f"(timeout={timeout}s, size={size_bytes / 1_048_576:.1f}MB): "\n                      f"{stderr_text.strip()[:200]}", serial)\n        time.sleep(2 ** attempt)\n    return False\n\n\n# --------------------------------------------------------------------------\n# power management — prevent headsets sleeping/dropping off wireless ADB\n# during a long sync or between showings at an event\n# --------------------------------------------------------------------------\n\ndef configure_power(serial: str, log: Log, keep_screen_on: bool = False,\n                     timeout_ms: int = DEFAULT_SCREEN_OFF_TIMEOUT_MS):\n    """Idempotent, cheap — safe to run on every sync.\n\n    Always applies WiFi never-sleep (wifi_sleep_policy=2,\n    wifi_suspend_optimizations_enabled=0) — by default Android can power\n    down or throttle the WiFi radio once idle, which is what silently\n    breaks the adb connection during a long sync or an idle period between\n    showings. This is "the actual fix" for that specific problem, and it\n    works regardless of screen state — these settings are standard through\n    Android 8 but were deprecated on later stock Android; Go\'s build is an\n    older, heavily modified fork, so this needs a one-headset test rather\n    than an assumption it\'s honored here.\n\n    keep_screen_on additionally disables the idle screen timeout ("stay\n    awake while charging" + the proximity-triggered auto-standby\n    broadcasts) — this forces the screen on for as long as the headset is\n    charging. Off by default: it isn\'t needed for ADB connectivity (WiFi\n    never-sleep above already covers that independent of screen state),\n    and forcing the screen on can outpace what some chargers can actually\n    supply, net-draining a headset that appears to be charging. Only turn\n    this on if you specifically want a headset visibly active/awake during\n    a sync (e.g. for on-site visual monitoring) and know the charger can\n    handle it. The two Oculus broadcasts here are undocumented\n    (`prox_close` / `automation_disable`) — their exact behavior was never\n    fully confirmed, only that they\'re part of the same shelf-sleep-\n    suppression intent as stayon.\n\n    NOTE: these settings, and stay-awake-while-charging specifically, were\n    briefly suspected and removed while chasing a headset self-wake issue\n    that traced back to a stale orphaned background process on the HOST\n    machine (a watchdog that survived the control panel app closing) --\n    fully unrelated to anything set on the device. Confirmed innocent of\n    THAT bug; the actual fix there was hardening subprocess cleanup (see\n    popen_in_own_group / --parent-pid handling). Made opt-in here for a\n    separate, later reason: it does exactly what it\'s documented to do\n    (force the screen on while charging), which is undesirable on\n    hardware where the charger can\'t outpace that draw."""\n    shell(serial, "settings put global wifi_sleep_policy 2", timeout=10)\n    shell(serial, "settings put global wifi_suspend_optimizations_enabled 0", timeout=10)\n    applied = "wifi never-sleep"\n\n    if keep_screen_on:\n        shell(serial, f"settings put system screen_off_timeout {timeout_ms}", timeout=10)\n        shell(serial, "svc power stayon true", timeout=10)  # most effective while charging\n        shell(serial, "am broadcast -a com.oculus.vrpowermanager.prox_close", timeout=10)\n        shell(serial, "am broadcast -a com.oculus.vrpowermanager.automation_disable", timeout=10)\n        applied += ", screen_off_timeout, stayon, proximity broadcasts"\n\n    log.line(f"power config applied ({applied})", serial)\n\n\n\ndef wake_pulse(serial: str):\n    """Non-destructive wake — keycode 224 lights the screen without the\n    toggle risk of the power button (keycode 26), which would put an\n    already-awake headset TO SLEEP instead of waking it."""\n    res = shell(serial, "input keyevent 224", timeout=10)\n    return res.returncode == 0\n\n\n# --------------------------------------------------------------------------\n# stale v3.local entry detection/cleanup\n#\n# Reverse-engineered from a live device, not documented by Headjack:\n# files/v3.local is the app\'s own record of "what have I downloaded" --\n# two parallel JSON arrays, "c" (content IDs) and "v" (the filename\n# downloaded for that ID, or "" if nothing\'s been fetched yet). It\'s\n# independent of the shared catalog (files/App/<id>.v3) and independent of\n# what\'s actually on disk -- if a file is deleted or never fully arrives\n# without going through the app\'s own removal path, v3.local can end up\n# claiming a download exists when the file behind it doesn\'t. This doesn\'t\n# affect playback (the app plays whatever file is actually in a content\n# ID\'s folder), but it does throw off download-status reporting, and\n# manually cloning a device\'s whole Android/data folder to a new headset\n# carries the stale entry along for the ride.\n#\n# Fix is the same one confirmed safe by hand on a live device: blank the\n# stale entry\'s filename in "v", matching the pattern already used for\n# content that\'s genuinely never been downloaded. Only ever touches "v"\n# values for entries where the corresponding file is confirmed absent --\n# never touches "c", never touches an entry whose file actually exists.\n# --------------------------------------------------------------------------\n\ndef find_and_clean_stale_v3local(serial: str, package: str, dry_run: bool, log: Log):\n    """Returns a dict: {skipped: str|None, checked: int, stale: [(id, filename), ...], cleaned: bool}.\n    skipped is set (with a reason) if v3.local is missing or doesn\'t match\n    the expected structure -- this never guesses at a different layout, it\n    just reports why it didn\'t act and leaves the device untouched."""\n    result = {"skipped": None, "checked": 0, "stale": [], "cleaned": False}\n    data_root = f"/sdcard/Android/data/{package}"\n    v3local_path = f"{data_root}/files/v3.local"\n\n    res = shell(serial, f"cat {shlex.quote(v3local_path)}", timeout=15)\n    if res.returncode != 0 or not (res.stdout or "").strip():\n        result["skipped"] = "v3.local not found or empty on this device"\n        return result\n\n    raw = res.stdout\n    had_bom = raw.startswith("\\ufeff")\n    if had_bom:\n        raw = raw[1:]\n\n    try:\n        data = json.loads(raw)\n    except json.JSONDecodeError as e:\n        result["skipped"] = f"v3.local did not parse as JSON ({e}) -- leaving it untouched"\n        return result\n\n    if not (isinstance(data, dict) and isinstance(data.get("c"), list)\n            and isinstance(data.get("v"), list) and len(data["c"]) == len(data["v"])):\n        result["skipped"] = "v3.local structure didn\'t match the expected {c:[...], v:[...]} shape -- leaving it untouched"\n        return result\n\n    ids, filenames = data["c"], data["v"]\n    result["checked"] = sum(1 for f in filenames if f)\n\n    # Batch-check every populated entry against both possible locations\n    # (an ID could be a video or a media/image item) in one round trip.\n    candidates = {}   # index -> (video_path, media_path)\n    check_paths = []\n    for i, (cid, fname) in enumerate(zip(ids, filenames)):\n        if not fname:\n            continue\n        video_path = f"{data_root}/files/Video/{cid}/{fname}"\n        media_path = f"{data_root}/files/Media/{cid}/{fname}"\n        candidates[i] = (video_path, media_path)\n        check_paths.extend([video_path, media_path])\n\n    if not check_paths:\n        return result   # nothing populated at all -- nothing to check\n\n    sizes = batched_size_check(serial, check_paths, log)\n    stale_indices = [i for i, (vp, mp) in candidates.items() if sizes.get(vp) is None and sizes.get(mp) is None]\n\n    for i in stale_indices:\n        result["stale"].append((ids[i], filenames[i]))\n        log.line(f"stale v3.local entry: {ids[i]} claims \'{filenames[i]}\' but no such file exists", serial)\n\n    if not stale_indices:\n        return result\n    if dry_run:\n        log.line(f"[dry-run] would clean {len(stale_indices)} stale v3.local entr"\n                  f"{\'y\' if len(stale_indices) == 1 else \'ies\'}", serial)\n        return result\n\n    fixed_filenames = list(filenames)\n    for i in stale_indices:\n        fixed_filenames[i] = ""\n    fixed_data = dict(data)\n    fixed_data["v"] = fixed_filenames\n    new_content = json.dumps(fixed_data, indent=4)\n    if had_bom:\n        new_content = "\\ufeff" + new_content\n\n    # Sanity-check our own output parses before touching the device, then\n    # back up the device\'s current file before overwriting it -- cheap\n    # insurance even though this is our own freshly-built JSON.\n    json.loads(new_content.lstrip("\\ufeff"))\n\n    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")\n    backup_path = f"{v3local_path}.bak.{timestamp}"\n    shell(serial, f"cp {shlex.quote(v3local_path)} {shlex.quote(backup_path)}", timeout=15)\n\n    with tempfile.NamedTemporaryFile(mode="w", suffix=".local", delete=False, encoding="utf-8") as tf:\n        tf.write(new_content)\n        tmp_path = tf.name\n    try:\n        push_res = run_adb(["-s", serial, "push", tmp_path, v3local_path], timeout=30)\n        if push_res.returncode != 0:\n            log.line(f"failed to push cleaned v3.local: {(push_res.stderr or \'\').strip()[:200]}", serial)\n            return result\n    finally:\n        os.unlink(tmp_path)\n\n    result["cleaned"] = True\n    log.line(f"cleaned {len(stale_indices)} stale v3.local entr"\n              f"{\'y\' if len(stale_indices) == 1 else \'ies\'} (backup: {backup_path})", serial)\n    return result\n\n\ndef derive_package_from_remote_path(path: str):\n    """Best-effort package name pulled from a /sdcard/Android/data/<package>/... path. Used as a\n    fallback for features that need the package name to locate files/v3.local or the app\'s\n    catalog, but only got --remote-target explicitly (e.g. pointing at a full device-clone root)\n    rather than --package -- which is a normal, supported way to run a sync, not an edge case:\n    remote_target still contains the package name either way, just at a fixed position in the\n    path rather than as its own argument. Returns None if the path doesn\'t contain an\n    Android/data/<package> segment."""\n    parts = Path(path).parts\n    if "Android" in parts:\n        idx = parts.index("Android")\n        if idx + 2 < len(parts) and parts[idx + 1] == "data":\n            return parts[idx + 2]\n    return None\n\n\ndef headjack_content_id_and_filename(remote_path: str):\n    """Given the absolute on-device path a file was (or would be) pushed to, return\n    (content_id, filename) if it falls under .../files/Video/<id>/<filename> or\n    .../files/Media/<id>/<filename> -- the ID Headjack\'s own catalog and v3.local key off of --\n    else None. Derived from the actual absolute remote path rather than the sync\'s relative path,\n    so it works the same regardless of which remote_target shape produced it (the app root in\n    --content-is-app-root mode, the files/Video-only default fallback, or an explicit clone-root\n    target as in a full device-clone sync) -- the substring this looks for is present in the\n    final absolute path in every case."""\n    for marker in ("/files/Video/", "/files/Media/"):\n        idx = remote_path.find(marker)\n        if idx != -1:\n            remainder = remote_path[idx + len(marker):].strip("/").split("/")\n            if len(remainder) >= 2 and remainder[0]:\n                return remainder[0], "/".join(remainder[1:])\n    return None\n\n\ndef register_pushed_content_in_v3local(serial: str, package: str, pushed_ids_and_filenames: dict,\n                                        dry_run: bool, log: Log):\n    """Marks freshly-pushed video/media content as installed in the app\'s own files/v3.local\n    bookkeeping (the {"c": [...content ids...], "v": [...downloaded filename or ""...]} record\n    Headjack\'s own in-app downloader normally maintains as it downloads each item). Content this\n    tool pushes directly over adb bypasses that downloader entirely -- the file is genuinely\n    present and plays fine, but the app\'s own installed-content record, and whatever it reports\n    upstream about what a given headset actually has installed, never learns about it unless\n    something updates v3.local too. This only ever fills in a previously-empty or\n    previously-absent entry for content this run just pushed and verified -- it never overwrites\n    an entry that\'s already non-empty, even to a different filename, since Headjack matches\n    content by ID folder, not filename (a non-empty "v" entry already means "installed" from the\n    app\'s point of view, whatever filename it happens to record). Mirrors\n    find_and_clean_stale_v3local()\'s read/validate/backup/write approach in the opposite\n    direction. Returns {"skipped": str|None, "registered": [(id, filename), ...]}."""\n    result = {"skipped": None, "registered": []}\n    if not pushed_ids_and_filenames:\n        return result\n\n    data_root = f"/sdcard/Android/data/{package}"\n    v3local_path = f"{data_root}/files/v3.local"\n\n    res = shell(serial, f"cat {shlex.quote(v3local_path)}", timeout=15)\n    if res.returncode != 0 or not (res.stdout or "").strip():\n        result["skipped"] = "v3.local not found or empty on this device"\n        return result\n\n    raw = res.stdout\n    had_bom = raw.startswith("\\ufeff")\n    if had_bom:\n        raw = raw[1:]\n\n    try:\n        data = json.loads(raw)\n    except json.JSONDecodeError as e:\n        result["skipped"] = f"v3.local did not parse as JSON ({e}) -- leaving it untouched"\n        return result\n\n    if not (isinstance(data, dict) and isinstance(data.get("c"), list)\n            and isinstance(data.get("v"), list) and len(data["c"]) == len(data["v"])):\n        result["skipped"] = ("v3.local structure didn\'t match the expected {c:[...], v:[...]} "\n                              "shape -- leaving it untouched")\n        return result\n\n    ids, filenames = list(data["c"]), list(data["v"])\n    index_by_id = {}\n    for i, cid in enumerate(ids):\n        index_by_id.setdefault(cid, i)   # first occurrence, same as find_and_clean_stale_v3local\n\n    for content_id, filename in pushed_ids_and_filenames.items():\n        i = index_by_id.get(content_id)\n        if i is not None:\n            if not filenames[i]:\n                filenames[i] = filename\n                result["registered"].append((content_id, filename))\n            # else: already marked downloaded (possibly under a different filename) --\n            # Headjack matches by ID, not filename, so this entry is left alone\n        else:\n            ids.append(content_id)\n            filenames.append(filename)\n            index_by_id[content_id] = len(ids) - 1\n            result["registered"].append((content_id, filename))\n\n    if not result["registered"]:\n        return result\n\n    summary = ", ".join(f"{cid} -> {fn}" for cid, fn in result["registered"][:8]) + (\n        f" (+{len(result[\'registered\']) - 8} more)" if len(result["registered"]) > 8 else "")\n\n    if dry_run:\n        log.line(f"[dry-run] would register {len(result[\'registered\'])} content ID(s) as "\n                  f"installed in v3.local: {summary}", serial)\n        result["registered"] = []\n        return result\n\n    fixed_data = dict(data)\n    fixed_data["c"] = ids\n    fixed_data["v"] = filenames\n    new_content = json.dumps(fixed_data, indent=4)\n    if had_bom:\n        new_content = "\\ufeff" + new_content\n    json.loads(new_content.lstrip("\\ufeff"))   # sanity-check our own output before touching the device\n\n    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")\n    backup_path = f"{v3local_path}.bak.{timestamp}"\n    shell(serial, f"cp {shlex.quote(v3local_path)} {shlex.quote(backup_path)}", timeout=15)\n\n    with tempfile.NamedTemporaryFile(mode="w", suffix=".local", delete=False, encoding="utf-8") as tf:\n        tf.write(new_content)\n        tmp_path = tf.name\n    try:\n        push_res = run_adb(["-s", serial, "push", tmp_path, v3local_path], timeout=30)\n        if push_res.returncode != 0:\n            log.line(f"failed to push updated v3.local: {(push_res.stderr or \'\').strip()[:200]}", serial)\n            result["registered"] = []\n            return result\n    finally:\n        os.unlink(tmp_path)\n\n    log.line(f"registered {len(result[\'registered\'])} content ID(s) as installed "\n              f"in v3.local (backup: {backup_path}): {summary}", serial)\n    return result\n\n\ndef register_all_known_content(serial, remote_target, effective_package, known_rels, args, log, result):\n    """Runs v3.local install-registration against every rel path we\'re confident is correctly\n    present on this device right now -- not just files pushed THIS run. This matters because a\n    file that was correctly pushed before this registration feature existed (or during any\n    earlier run whose diff didn\'t happen to re-touch it) sits correctly on disk forever, while\n    Headjack\'s installed-content record stays empty for it: it never re-enters `to_push` on a\n    later run to trigger a narrower check, since the diff correctly sees it as already matching.\n    Safe to call on every run regardless of whether anything was pushed:\n    register_pushed_content_in_v3local() itself only ever fills a still-empty entry and writes\n    nothing at all once every known ID is already marked installed, so a fully-registered device\n    costs one cheap `cat` and nothing else on every subsequent run."""\n    if getattr(args, "skip_install_registration", False):\n        return\n    if not effective_package:\n        return\n    ids_and_filenames = {}\n    for rel in known_rels:\n        parsed = headjack_content_id_and_filename(str(Path(remote_target, rel)))\n        if parsed:\n            content_id, filename = parsed\n            ids_and_filenames[content_id] = filename\n    if not ids_and_filenames:\n        return\n    reg_result = register_pushed_content_in_v3local(\n        serial, effective_package, ids_and_filenames, args.dry_run, log)\n    result["v3local_registered"] = reg_result["registered"]\n    if reg_result["skipped"]:\n        log.line(f"install-registration skipped: {reg_result[\'skipped\']}", serial)\n\n\n# --------------------------------------------------------------------------\n# local content-ID cross-check against the app\'s own catalog\n#\n# Headjack organizes video/media content on-device by opaque content ID\n# (files/Video/<content-id>/<any-filename>) -- that ID comes from Headjack\'s\n# own CMS (files/App/<app-id>.v3), not something generated locally. A local\n# content folder is expected to mirror that same ID-per-folder structure.\n# If a local folder\'s name is a typo, or content that was removed from the\n# catalog but never cleaned up locally, it\'ll get pushed successfully (sync\n# has no way to know it\'s wrong on its own) but the app will never show or\n# play it, since playback is driven entirely by what the catalog\n# references -- not by what happens to exist on disk. This is a\n# best-effort, informational check: warns, never blocks a push, since a\n# device\'s catalog could plausibly be mid-update or briefly unreachable.\n# --------------------------------------------------------------------------\n\ndef check_local_ids_against_catalog(serial: str, package: str, local_manifest: dict, log: Log):\n    data_root = f"/sdcard/Android/data/{package}"\n    find_res = shell(serial, f"find {shlex.quote(data_root + \'/files/App\')} -maxdepth 1 -name \'*.v3\'",\n                      timeout=15)\n    catalog_candidates = [line.strip() for line in (find_res.stdout or "").splitlines() if line.strip()]\n    if find_res.returncode != 0 or not catalog_candidates:\n        log.line("could not locate the app\'s .v3 catalog file -- skipping content-ID cross-check", serial)\n        return\n    catalog_path = catalog_candidates[0]\n\n    cat_res = shell(serial, f"cat {shlex.quote(catalog_path)}", timeout=15)\n    if cat_res.returncode != 0 or not (cat_res.stdout or "").strip():\n        log.line("could not read the app\'s .v3 catalog -- skipping content-ID cross-check", serial)\n        return\n\n    raw = cat_res.stdout\n    if raw.startswith("\\ufeff"):\n        raw = raw[1:]\n    try:\n        catalog = json.loads(raw)\n    except json.JSONDecodeError:\n        log.line("app\'s .v3 catalog did not parse as JSON -- skipping content-ID cross-check", serial)\n        return\n\n    known_ids = set()\n    for section in ("Video", "Media"):\n        for item in (catalog.get(section) or []):\n            if isinstance(item, dict) and "Id" in item:\n                known_ids.add(item["Id"])\n    if not known_ids:\n        log.line("app\'s .v3 catalog had no recognizable Video/Media IDs -- skipping content-ID cross-check",\n                  serial)\n        return\n\n    local_top_level_ids = {rel.split("/", 1)[0] for rel in local_manifest if "/" in rel}\n    unknown = sorted(local_top_level_ids - known_ids)\n    if unknown:\n        shown = ", ".join(unknown[:10]) + (f" (+{len(unknown) - 10} more)" if len(unknown) > 10 else "")\n        log.line(f"WARNING: {len(unknown)} local folder(s) don\'t match any ID in the app\'s own catalog "\n                  f"-- these will be pushed but won\'t show up or play, since the app is driven by its "\n                  f"catalog, not by what\'s physically present: {shown}", serial)\n    else:\n        log.line(f"content-ID cross-check OK: all {len(local_top_level_ids)} local folder(s) match "\n                  f"known catalog IDs", serial)\n\n\n# --------------------------------------------------------------------------\n# per-device sync\n# --------------------------------------------------------------------------\n\ndef sync_device(serial, local_manifest, content_dir, remote_target, state_dir,\n                 args, log: Log):\n    t0 = time.time()\n    result = {"device": serial, "pushed": 0, "failed": 0, "skipped_all": False,\n              "deleted": 0, "failed_files": [], "skipped_low_storage": [], "error": None,\n              "stale_v3local_cleaned": [], "v3local_registered": [],\n              "reserved_space_suspected": False}\n\n    # --- ensure device is actually reachable, with reconnect retries ---\n    alive = device_alive(serial)\n    for attempt in range(DEVICE_RETRIES):\n        if alive:\n            break\n        if ":" in serial:  # wireless serial, e.g. ip:port -> can retry connect\n            adb_connect(serial, log)\n            time.sleep(2)\n        alive = device_alive(serial)\n    if not alive:\n        result["error"] = "unreachable"\n        log.line("UNREACHABLE — skipping", serial)\n        return result\n\n    if not args.skip_power_config and not args.dry_run:\n        configure_power(serial, log, keep_screen_on=args.keep_screen_on)\n\n    effective_package = args.package or derive_package_from_remote_path(remote_target)\n\n    if getattr(args, "clean_stale_metadata", False):\n        if not effective_package:\n            log.line("--clean-stale-metadata needs the app\'s package (neither --package nor "\n                      "derivable from --remote-target) -- skipping this check", serial)\n        else:\n            stale_result = find_and_clean_stale_v3local(serial, effective_package, args.dry_run, log)\n            result["stale_v3local_cleaned"] = stale_result["stale"] if stale_result["cleaned"] else []\n            if stale_result["skipped"]:\n                log.line(f"stale-metadata check skipped: {stale_result[\'skipped\']}", serial)\n\n    if getattr(args, "check_catalog_ids", False):\n        if not effective_package:\n            log.line("--check-catalog-ids needs the app\'s package (neither --package nor "\n                      "derivable from --remote-target) -- skipping this check", serial)\n        else:\n            check_local_ids_against_catalog(serial, effective_package, local_manifest, log)\n\n    # --- decide whether we can trust cached state or need remote truth ---\n    state = load_device_state(state_dir, serial)\n    need_remote_check = args.verify or state is None\n\n    if not need_remote_check:\n        known = state["manifest"]\n        to_push, to_delete, _skipped_protected = diff_manifests(local_manifest, known)\n        if not to_push and not (args.prune and to_delete):\n            result["skipped_all"] = True\n            log.line(f"up to date (trusted state, {len(local_manifest)} files) — nothing to do", serial)\n            register_all_known_content(serial, remote_target, effective_package, known.keys(), args, log, result)\n            return result\n        log.line(f"trusted-state diff: {len(to_push)} to push, {len(to_delete)} extra on device", serial)\n    else:\n        scan_method = "hash (--verify-hash)" if args.verify_hash else "size (default, fast)"\n        log.line(f"no trusted state (or --verify set) — doing full remote reconciliation "\n                  f"[{scan_method}]", serial)\n        if args.verify_hash:\n            remote_manifest = remote_md5_manifest(serial, remote_target, log)\n            compare_by = "md5"\n        else:\n            remote_manifest = remote_size_manifest(serial, remote_target, log)\n            compare_by = "size"\n\n        if remote_manifest is None:\n            # Scan failed or timed out -- we genuinely don\'t know what\'s on\n            # this device. Proceeding as if it\'s empty is exactly the bug\n            # that caused every real file to look missing and get\n            # needlessly re-pushed. Abort this device for this run rather\n            # than guess.\n            result["error"] = "remote_scan_failed"\n            log.line("ABORTING this device for this run — could not determine what\'s actually on "\n                      "it, refusing to guess (which would risk re-pushing content that\'s already "\n                      "there correctly). Re-run, or use --verify-hash if you suspect a size "\n                      "collision specifically.", serial)\n            return result\n\n        if getattr(args, "content_is_app_root", False):\n            # The local scan only ever looked under files/Video and\n            # files/Media (see build_local_manifest\'s scan_subdirs), but\n            # remote_target here is the whole app root, so this raw scan\n            # includes everything else under it too -- cache/, il2cpp/,\n            # the manifests, and anything else Unity/Headjack happens to\n            # keep there that we\'ve never seen and so isn\'t on the\n            # protected list. Comparing against the unfiltered scan would\n            # make all of that look like "extra on device" and, with\n            # --prune, delete it -- files a curated local folder was never\n            # trying to represent one way or the other. Restrict the\n            # comparison to the same two subtrees the local scan covers,\n            # matching what local_manifest could possibly agree or\n            # disagree with.\n            remote_manifest = {rel: v for rel, v in remote_manifest.items()\n                                if rel.startswith(("files/Video/", "files/Media/"))}\n\n        to_push, to_delete, _skipped_protected = diff_manifests(local_manifest, remote_manifest, compare_by)\n        log.line(f"remote reconciliation: {len(to_push)} to push, {len(to_delete)} extra on device", serial)\n\n    if args.dry_run:\n        for rel in to_push:\n            log.line(f"[dry-run] would push: {rel}", serial)\n        if args.prune:\n            for rel in to_delete:\n                log.line(f"[dry-run] would delete: {rel}", serial)\n        register_all_known_content(serial, remote_target, effective_package, local_manifest.keys(),\n                                    args, log, result)\n        return result\n\n    # --- make sure target directories exist (batched) ---\n    if to_push:\n        needed_dirs = {str(Path(remote_target, rel).parent) for rel in to_push}\n        batched_mkdir(serial, needed_dirs, log)\n\n    # --- free-space accounting: overwriting frees the old file\'s blocks as\n    # the new one is written, so the cost of each push is just the *delta*\n    # (new_size - old_size), not the full new file size. We check existing\n    # remote sizes up front, then track a running estimate so we never start\n    # a push that would run the device out of space mid-transfer. ---\n    margin_bytes = args.min_free_mb * 1024 * 1024\n    final_manifest = dict(state["manifest"]) if state and not need_remote_check else {}\n\n    if to_push:\n        remote_paths = [str(Path(remote_target, rel)) for rel in to_push]\n        existing_sizes = batched_size_check(serial, remote_paths, log)\n        free_bytes = get_free_bytes(serial, log=log)\n        if free_bytes is not None:\n            log.line(f"free space: {free_bytes / 1_048_576:.0f} MB (margin kept: {args.min_free_mb} MB)", serial)\n\n        def delta_for(rel):\n            existing = existing_sizes.get(str(Path(remote_target, rel))) or 0\n            return local_manifest[rel]["size"] - existing\n\n        # Smallest space requirement first, so a tight device gets as many\n        # files updated as possible rather than stalling on one big file.\n        ordered = sorted(to_push, key=delta_for)\n        running_free = free_bytes  # may be None -> space checks skipped below\n        failed_record = load_failed_pushes(state_dir, serial)\n        failed_record_changed = False\n\n        for rel in ordered:\n            local_path = content_dir / rel\n            remote_path = str(Path(remote_target, rel))\n            existing_before = existing_sizes.get(remote_path) or 0\n            delta = local_manifest[rel]["size"] - existing_before\n\n            if running_free is not None and delta > 0 and (running_free - delta) < margin_bytes:\n                log.line(f"SKIP (low storage): {rel} needs +{delta / 1_048_576:.1f} MB, "\n                          f"only {running_free / 1_048_576:.1f} MB free", serial)\n                result["skipped_low_storage"].append(rel)\n                prior_failure = failed_record.get(rel)\n                if prior_failure and existing_before == 0:\n                    # Nothing is visible at this path to overwrite (if a partial file were\n                    # there, its size would already have been credited in `delta` above), yet\n                    # a push of this exact file failed on this device earlier. That combination\n                    # is the signature of space still held by the aborted transfer\'s deleted\n                    # partial file -- invisible to stat, still counted by df, released on reboot.\n                    result["reserved_space_suspected"] = True\n                    log.line(f"  ^ a push of this file failed on this device before ({prior_failure.get(\'at\')}) "\n                              f"and no partial copy is visible at its path now -- the aborted transfer\'s "\n                              f"space is likely still reserved on the headset. REBOOT THIS HEADSET and "\n                              f"re-run; free space should come back without deleting anything.", serial)\n                continue\n\n            log.line(f"pushing {rel} ({local_manifest[rel][\'size\'] / 1_048_576:.1f} MB, "\n                      f"delta {delta / 1_048_576:+.1f} MB)", serial)\n            ok = push_one(serial, local_path, remote_path, log)\n            if ok:\n                result["pushed"] += 1\n                final_manifest[rel] = local_manifest[rel]["md5"]\n                if running_free is not None:\n                    running_free -= delta\n                if rel in failed_record:\n                    del failed_record[rel]\n                    failed_record_changed = True\n            else:\n                result["failed"] += 1\n                result["failed_files"].append(rel)\n                failed_record[rel] = {"size": local_manifest[rel]["size"], "at": now_iso()}\n                failed_record_changed = True\n                # leave it out of final_manifest so it\'s retried next run\n                log.line(f"FAILED after retries: {rel} — will retry next run", serial)\n                # A failed push can still hold real space after it dies: either as a visible\n                # partial file at remote_path, or -- as seen in practice -- as a partial file\n                # adbd already deleted but the headset still holds open, which stat can\'t see but\n                # df still counts. The running estimate above only changes on success, so re-query\n                # df itself (authoritative in both cases) rather than inferring from the file\'s\n                # visible size, and use that for the rest of this batch.\n                if running_free is not None:\n                    fresh_free = get_free_bytes(serial, log=log)\n                    visible_after = batched_size_check(serial, [remote_path], log).get(remote_path) or 0\n                    visible_change = visible_after - existing_before\n                    if fresh_free is not None:\n                        consumed = running_free - fresh_free\n                        reserved = consumed - visible_change\n                        if visible_change:\n                            log.line(f"partial file left at {rel}: {visible_after / 1_048_576:.1f} MB "\n                                      f"(overwriting it next time is credited against the space needed)",\n                                      serial)\n                        if reserved > 50 * 1_048_576:\n                            result["reserved_space_suspected"] = True\n                            log.line(f"free space dropped {consumed / 1_048_576:.1f} MB during the failed "\n                                      f"push, but only {visible_change / 1_048_576:.1f} MB of that is a "\n                                      f"visible file -- ~{reserved / 1_048_576:.0f} MB is likely held by the "\n                                      f"aborted transfer until this headset is rebooted", serial)\n                        running_free = fresh_free\n                    else:\n                        running_free -= visible_change\n\n        if failed_record_changed:\n            save_failed_pushes(state_dir, serial, failed_record)\n\n        if result["skipped_low_storage"]:\n            if result.get("reserved_space_suspected"):\n                log.line(f"{len(result[\'skipped_low_storage\'])} file(s) skipped due to low storage — "\n                          f"this headset likely has space held by an earlier failed push: reboot it "\n                          f"and re-run before deleting any content", serial)\n            else:\n                log.line(f"{len(result[\'skipped_low_storage\'])} file(s) skipped due to low storage — "\n                          f"free up space (e.g. --prune old content) and re-run", serial)\n\n    # unchanged files: carry forward into the new trusted manifest\n    for rel, info in local_manifest.items():\n        if rel not in to_push:\n            final_manifest[rel] = info["md5"]\n\n    # --- optional prune of files no longer in local content ---\n    if args.prune and to_delete:\n        for rel in to_delete:\n            remote_path = str(Path(remote_target, rel))\n            res = shell(serial, f"rm -f {shlex.quote(remote_path)}", timeout=20)\n            if res.returncode == 0:\n                result["deleted"] += 1\n            else:\n                log.line(f"prune FAILED: {rel} (rm exit {res.returncode}) — left in place, will "\n                          f"be reconsidered next run", serial)\n\n    # --- lightweight post-push verification (size check, batched) ---\n    if result["pushed"] and not result["failed"]:\n        pushed_paths = [str(Path(remote_target, rel)) for rel in to_push if rel not in result["failed_files"]]\n        sizes = batched_size_check(serial, pushed_paths, log)\n        for rel in to_push:\n            if rel in result["failed_files"]:\n                continue\n            remote_path = str(Path(remote_target, rel))\n            expected = local_manifest[rel]["size"]\n            actual = sizes.get(remote_path)\n            if actual != expected:\n                log.line(f"VERIFY MISMATCH {rel}: expected {expected}B got {actual}", serial)\n                result["failed"] += 1\n                result["failed_files"].append(rel)\n                final_manifest.pop(rel, None)\n\n    # --- register all currently-known-correct content as "installed" in the app\'s own\n    # v3.local bookkeeping (not just what was pushed this run -- see\n    # register_all_known_content() for why that distinction matters). Content this tool\n    # pushes directly bypasses Headjack\'s own downloader, which is normally what writes\n    # this record -- without this step a file can be present and play fine while the app\n    # (and anything it reports upstream about what this headset has installed) never\n    # learns about it. ---\n    register_all_known_content(serial, remote_target, effective_package, final_manifest.keys(), args, log, result)\n\n    # only persist trusted state if nothing failed verification-wise on this run\n    if not result["failed_files"]:\n        save_device_state(state_dir, serial, final_manifest)\n    else:\n        # still save, but future runs will re-diff the failed ones since their\n        # hash is missing from final_manifest\n        save_device_state(state_dir, serial, final_manifest)\n\n    dt = time.time() - t0\n    log.line(f"DONE pushed={result[\'pushed\']} failed={result[\'failed\']} "\n             f"deleted={result[\'deleted\']} ({dt:.1f}s)", serial)\n    return result\n\n\n# --------------------------------------------------------------------------\n# standalone keepalive watchdog\n# --------------------------------------------------------------------------\n\ndef parent_alive(pid):\n    """True if pid is still a running process, or if pid is None (not being\n    monitored, e.g. run by hand from a terminal)."""\n    if pid is None:\n        return True\n    try:\n        os.kill(pid, 0)\n        return True\n    except OSError:\n        return False\n\n\ndef interruptible_sleep(total_seconds, parent_pid, chunk=5):\n    """Sleeps in small chunks, checking parent liveness between each, so an\n    orphaned watchdog dies within seconds of its parent going away instead\n    of waiting out the full (possibly long) interval first. Returns False\n    if the parent died mid-sleep."""\n    elapsed = 0\n    while elapsed < total_seconds:\n        if not parent_alive(parent_pid):\n            return False\n        this_chunk = min(chunk, total_seconds - elapsed)\n        time.sleep(this_chunk)\n        elapsed += this_chunk\n    return True\n\n\n# --------------------------------------------------------------------------\n# bandwidth/bottleneck diagnostic mode\n#\n# Automates the manual test sequence used to figure out whether wireless\n# throughput (vs. the operator laptop\'s own uplink, vs. per-headset radio\n# quality) is actually the limiting factor on sync speed: (1) the laptop\'s\n# own network link type/speed, (2) a single-device baseline push with zero\n# contention, (3) the same push repeated at increasing concurrency to see\n# whether AGGREGATE throughput keeps scaling or plateaus, and (4) each\n# tested headset\'s WiFi signal/link-speed/band. Doesn\'t touch any real\n# content -- generates its own random test file (random, not all-zero, so\n# nothing downstream can take a shortcut on highly compressible data) and\n# cleans up after itself both locally and on every device it touched.\n# --------------------------------------------------------------------------\n\n_ADB_PUSH_RATE_RE = re.compile(r"([\\d.]+)\\s*MB/s\\s*\\((\\d+)\\s*bytes\\s*in\\s*([\\d.]+)s?\\)")\n\n\ndef check_operator_network_link(target_ip: str, log: Log):\n    """Best-effort, Linux-only (uses `ip`/`ethtool`/`iw`): reports the\n    negotiated speed of whichever local interface reaches target_ip.\n    Gracefully skips with a clear message on any other OS or if the\n    relevant tools aren\'t installed -- this is diagnostic sugar, not\n    worth failing the whole run over."""\n    try:\n        route = subprocess.run(["ip", "route", "get", target_ip], capture_output=True, text=True, timeout=5)\n    except (FileNotFoundError, OSError):\n        log.line("laptop network check skipped (`ip` command not available -- likely not Linux)")\n        return\n    if route.returncode != 0:\n        log.line(f"laptop network check: could not determine the route to {target_ip}")\n        return\n    m = re.search(r"dev (\\S+)", route.stdout)\n    if not m:\n        log.line("laptop network check: could not parse the outgoing interface from `ip route get`")\n        return\n    iface = m.group(1)\n\n    try:\n        eth = subprocess.run(["ethtool", iface], capture_output=True, text=True, timeout=5)\n        if eth.returncode == 0 and "Speed:" in eth.stdout:\n            speed_line = next((l.strip() for l in eth.stdout.splitlines() if "Speed:" in l), "")\n            log.line(f"laptop network: {iface} (wired) -- {speed_line}")\n            return\n    except (FileNotFoundError, OSError):\n        pass\n\n    try:\n        iw = subprocess.run(["iw", "dev", iface, "link"], capture_output=True, text=True, timeout=5)\n        if iw.returncode == 0 and iw.stdout.strip():\n            bitrate = next((l.strip() for l in iw.stdout.splitlines() if "bitrate" in l.lower()), None)\n            signal = next((l.strip() for l in iw.stdout.splitlines() if "signal" in l.lower()), None)\n            log.line(f"laptop network: {iface} (WiFi) -- {bitrate or \'rate unknown\'}, "\n                      f"{signal or \'signal unknown\'}")\n            log.line("NOTE: the operator laptop itself is on WiFi -- every concurrent push shares "\n                      "this one uplink before it even reaches the router, which can be a tighter "\n                      "bottleneck than any individual headset\'s own connection.")\n            return\n    except (FileNotFoundError, OSError):\n        pass\n\n    log.line(f"laptop network: could not determine link speed for {iface} "\n              f"(neither ethtool nor `iw` gave usable output)")\n\n\ndef generate_bandwidth_test_file(size_mb: int, log: Log) -> Path:\n    path = Path(tempfile.gettempdir()) / f"cxvr_bwtest_{os.getpid()}.bin"\n    log.line(f"generating a {size_mb}MB random test file (random, not all-zero, so nothing "\n              f"downstream can shortcut on compressible data)...")\n    with open(path, "wb") as f:\n        for _ in range(size_mb):\n            f.write(os.urandom(1024 * 1024))\n    return path\n\n\ndef timed_push(serial: str, local_path: Path, remote_path: str):\n    """Returns {serial, success, elapsed_s, reported_mb_s, error}.\n    reported_mb_s comes from parsing adb\'s own summary line when possible,\n    falling back to size/elapsed if that line isn\'t found in its output."""\n    size = local_path.stat().st_size\n    t0 = time.time()\n    res = run_adb(["-s", serial, "push", str(local_path), remote_path], timeout=push_timeout_for(size))\n    elapsed = time.time() - t0\n    if res.returncode != 0:\n        return {"serial": serial, "success": False, "elapsed_s": elapsed, "reported_mb_s": None,\n                "error": (res.stderr or "").strip()[:200]}\n\n    combined = (res.stdout or "") + (res.stderr or "")\n    m = _ADB_PUSH_RATE_RE.search(combined)\n    if m:\n        reported = float(m.group(1))\n    elif elapsed > 0:\n        reported = round((size / (1024 * 1024)) / elapsed, 1)\n    else:\n        reported = None\n    return {"serial": serial, "success": True, "elapsed_s": elapsed, "reported_mb_s": reported, "error": None}\n\n\ndef get_wifi_link_info(serial: str, log: Log):\n    """Best-effort parse of `dumpsys wifi` -- format varies significantly\n    across Android versions, so this tries several plausible field-name\n    spellings and returns whatever it found rather than assuming one\n    exact layout."""\n    res = shell(serial, "dumpsys wifi", timeout=15)\n    if res.returncode != 0 or not (res.stdout or "").strip():\n        return {"serial": serial, "rssi": None, "link_speed": None, "frequency": None}\n\n    text = res.stdout\n    rssi = link_speed = frequency = None\n    for pat in (r"RSSI[:\\s]+(-?\\d+)", r"rssi[=:\\s]+(-?\\d+)"):\n        m = re.search(pat, text)\n        if m:\n            rssi = int(m.group(1))\n            break\n    for pat in (r"Link speed[:\\s]+(-?\\d+)", r"LinkSpeed[:\\s]+(-?\\d+)"):\n        m = re.search(pat, text, re.IGNORECASE)\n        if m:\n            link_speed = int(m.group(1))\n            break\n    for pat in (r"Frequency[:\\s]+(\\d+)", r"frequency[=:\\s]+(\\d+)"):\n        m = re.search(pat, text, re.IGNORECASE)\n        if m:\n            frequency = int(m.group(1))\n            break\n    return {"serial": serial, "rssi": rssi, "link_speed": link_speed, "frequency": frequency}\n\n\ndef run_bandwidth_diagnostic(args):\n    state_dir = Path(args.state_dir)\n    state_dir.mkdir(parents=True, exist_ok=True)\n    log = Log(state_dir / "logs" / f"{datetime.now():%Y%m%d_%H%M%S}_diagnostic.log")\n    log.line("=== BANDWIDTH DIAGNOSTIC MODE ===")\n\n    if args.connect_file:\n        for line in Path(args.connect_file).read_text().splitlines():\n            line = line.strip()\n            if line:\n                adb_connect(line, log)\n\n    all_devices = adb_devices()\n    allow = set(args.devices.split(",")) if args.devices else None\n    ready = [s for s in all_devices if device_alive(s) and (not allow or s in allow)]\n    if not ready:\n        log.line("no ready devices found -- aborting diagnostic")\n        sys.exit(1)\n    log.line(f"{len(ready)} device(s) available for testing: {\', \'.join(ready)}")\n\n    check_operator_network_link(ready[0].split(":")[0], log)\n\n    test_file = generate_bandwidth_test_file(args.diagnose_file_size_mb, log)\n    remote_name = f"/sdcard/{test_file.name}"\n    pushed_to = []\n    scaling_results = {}\n\n    try:\n        log.line("--- baseline: single device, zero contention ---")\n        baseline = timed_push(ready[0], test_file, remote_name)\n        if baseline["success"]:\n            pushed_to.append(ready[0])\n            log.line(f"{ready[0]}: {baseline[\'reported_mb_s\']} MB/s ({baseline[\'elapsed_s\']:.1f}s)")\n        else:\n            log.line(f"{ready[0]}: FAILED -- {baseline[\'error\']}")\n        shell(ready[0], f"rm -f {shlex.quote(remote_name)}", timeout=15)\n        pushed_to = [s for s in pushed_to if s != ready[0]]\n        scaling_results[1] = [baseline] if baseline["success"] else []\n\n        max_level = min(args.workers, len(ready))\n        for n in sorted(set(l for l in (2, 4, max_level) if 1 < l <= max_level)):\n            devices_this_level = ready[:n]\n            log.line(f"--- concurrency test: {n} device(s) simultaneously ---")\n            level_results = []\n            with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:\n                futures = {pool.submit(timed_push, s, test_file, remote_name): s for s in devices_this_level}\n                for fut in concurrent.futures.as_completed(futures):\n                    s = futures[fut]\n                    r = fut.result()\n                    level_results.append(r)\n                    if r["success"]:\n                        pushed_to.append(s)\n                        log.line(f"  {s}: {r[\'reported_mb_s\']} MB/s ({r[\'elapsed_s\']:.1f}s)")\n                    else:\n                        log.line(f"  {s}: FAILED -- {r[\'error\']}")\n            scaling_results[n] = level_results\n            for s in devices_this_level:\n                shell(s, f"rm -f {shlex.quote(remote_name)}", timeout=15)\n            pushed_to = [s for s in pushed_to if s not in devices_this_level]\n\n        log.line("--- WiFi link quality per headset ---")\n        for s in ready[:max_level]:\n            info = get_wifi_link_info(s, log)\n            parts = []\n            if info["rssi"] is not None:\n                parts.append(f"RSSI {info[\'rssi\']} dBm")\n            if info["link_speed"] is not None:\n                parts.append(f"link speed {info[\'link_speed\']} Mbps")\n            if info["frequency"] is not None:\n                band = "5GHz" if info["frequency"] > 3000 else "2.4GHz"\n                parts.append(f"{info[\'frequency\']} MHz ({band})")\n            log.line(f"  {s}: " + (", ".join(parts) if parts else "could not parse dumpsys wifi output "\n                                                                    "-- format may differ on this Android version"))\n\n        log.line("=" * 70)\n        log.line("ANALYSIS")\n        log.line("=" * 70)\n        aggregates = {}\n        for n, results in sorted(scaling_results.items()):\n            successful = [r for r in results if r["success"] and r["reported_mb_s"]]\n            aggregates[n] = sum(r["reported_mb_s"] for r in successful)\n            avg = aggregates[n] / len(successful) if successful else 0\n            log.line(f"N={n}: per-device avg {avg:.1f} MB/s | aggregate {aggregates[n]:.1f} MB/s "\n                      f"({len(successful)}/{len(results)} succeeded)")\n\n        agg_values = [v for v in aggregates.values() if v > 0]\n        if len(agg_values) >= 2:\n            growth = (agg_values[-1] - agg_values[0]) / agg_values[0]\n            if growth < 0.25:\n                log.line(f"Aggregate throughput barely moved ({agg_values[0]:.1f} -> {agg_values[-1]:.1f} "\n                          f"MB/s) as concurrency increased -- points to a SHARED ceiling (the laptop\'s "\n                          f"own uplink, or the access point itself), not per-device radio limits. "\n                          f"Increasing --workers further is unlikely to increase total throughput -- "\n                          f"it\'ll mainly split the same total bandwidth across more simultaneous transfers.")\n            else:\n                log.line(f"Aggregate throughput scaled with concurrency ({agg_values[0]:.1f} -> "\n                          f"{agg_values[-1]:.1f} MB/s) -- there\'s still headroom. Increasing --workers "\n                          f"beyond {max_level} may genuinely help, up to whatever level it eventually "\n                          f"plateaus at.")\n        else:\n            log.line("Only one concurrency level was testable (not enough devices connected right now) "\n                      "-- reconnect more headsets for a real scaling comparison.")\n    finally:\n        for s in set(pushed_to):\n            shell(s, f"rm -f {shlex.quote(remote_name)}", timeout=15)\n        try:\n            test_file.unlink()\n        except OSError:\n            pass\n\n    log.line("diagnostic complete")\n\n\ndef run_keepalive(args):\n    """Long-running loop: every --interval seconds, reconnect any known\n    wireless headsets and send a non-destructive wake pulse to each reachable\n    device. This is a backup to --skip-power-config=False (which disables\n    the sleep timer outright) — settings can get reset by a reboot or an app\n    crash, so this catches a headset that quietly went to sleep and dropped\n    off wireless ADB, rather than finding out at show time.\n\n    Self-terminates if --parent-pid was given and that process is no longer\n    running -- hardens against exactly the failure mode that once let an\n    orphaned watchdog outlive the control panel app closing (crash,\n    force-quit, anything short of this process itself being killed) and\n    keep waking headsets with nothing visibly running to blame."""\n    state_dir = Path(args.state_dir)\n    state_dir.mkdir(parents=True, exist_ok=True)\n    log = Log(state_dir / "logs" / f"keepalive_{datetime.now():%Y%m%d_%H%M%S}.log")\n    log.line(f"keepalive watchdog starting, interval={args.interval}s, "\n              f"parent_pid={args.parent_pid or \'not monitored\'}")\n\n    try:\n        while True:\n            if not parent_alive(args.parent_pid):\n                log.line(f"parent process (PID {args.parent_pid}) is gone -- keepalive exiting")\n                log.close()\n                return\n\n            if args.connect_file:\n                for line in Path(args.connect_file).read_text().splitlines():\n                    hp = line.strip()\n                    if hp and not hp.startswith("#"):\n                        adb_connect(hp, log)\n                time.sleep(2)\n\n            devices = adb_devices()\n            ready = [s for s, st in devices.items() if st == "device"]\n            if args.devices:\n                allow = set(x.strip() for x in args.devices.split(","))\n                ready = [s for s in ready if s in allow]\n\n            ok_count, fail_count = 0, 0\n            for s in ready:\n                if wake_pulse(s):\n                    ok_count += 1\n                else:\n                    fail_count += 1\n                    log.line("wake pulse FAILED — device may be asleep/unreachable", s)\n\n            unreachable = set(devices) - set(ready)\n            log.line(f"cycle complete: {ok_count} woken ok, {fail_count} failed, "\n                      f"{len(unreachable)} not in \'device\' state ({\', \'.join(sorted(unreachable)) or \'none\'})")\n\n            if not interruptible_sleep(args.interval, args.parent_pid):\n                log.line(f"parent process (PID {args.parent_pid}) is gone -- keepalive exiting")\n                log.close()\n                return\n    except KeyboardInterrupt:\n        log.line("keepalive watchdog stopped by user")\n        log.close()\n\n\n# --------------------------------------------------------------------------\n# main\n# --------------------------------------------------------------------------\n\ndef main():\n    ap = argparse.ArgumentParser(description="Sync VR content to a fleet of headsets over wireless ADB.")\n    ap.add_argument("--content-dir", help="Local folder containing the content to push (not needed for --keepalive)")\n    ap.add_argument("--content-is-app-root", action="store_true",\n                     help="Treat --content-dir as the app\'s own root folder (matching the on-device "\n                          "layout, e.g. a folder named after the package containing files/, cache/, "\n                          "manifest.tsv, etc.) rather than a folder curated to contain only sync-worthy "\n                          "content. Only files/Video and files/Media underneath it are scanned/synced -- "\n                          "everything else (Unity\'s shader cache, il2cpp runtime metadata, v3.local, the "\n                          "manifests) is never even scanned, let alone pushed. Needs --package (to derive "\n                          "the on-device app root) unless --remote-target is also given explicitly.")\n    ap.add_argument("--package", help="App package name; remote target becomes /sdcard/Android/data/<package>")\n    ap.add_argument("--remote-target", help="Explicit remote target dir (overrides --package)")\n    ap.add_argument("--workers", type=int, default=6, help="Max headsets synced in parallel (default 6)")\n    ap.add_argument("--verify", action="store_true",\n                     help="Force a full remote reconciliation on every device, instead of trusting "\n                          "cached state from a previous run. Uses the fast size-based scan by default "\n                          "(see --verify-hash for the slower, byte-exact alternative).")\n    ap.add_argument("--verify-hash", action="store_true",\n                     help="Use a full MD5 content hash for remote reconciliation instead of the default "\n                          "size-based scan. Byte-exact, but reads and hashes every file\'s full contents "\n                          "on the headset\'s own CPU -- can genuinely take minutes for many GB of video "\n                          "and may time out, in which case the device is skipped for that run rather "\n                          "than risking an unnecessary full re-push. The size-based default is dramatically "\n                          "cheaper and, in practice, just as reliable for detecting real content changes.")\n    ap.add_argument("--prune", action="store_true", help="Delete remote files not present locally")\n    ap.add_argument("--dry-run", action="store_true", help="Show what would happen, change nothing")\n    ap.add_argument("--devices", help="Comma-separated allow-list of serials to restrict this run to")\n    ap.add_argument("--connect-file", help="File of host:port lines to `adb connect` before scanning devices")\n    ap.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR), help="Where trusted state/cache is stored")\n    ap.add_argument("--min-free-mb", type=int, default=DEFAULT_MIN_FREE_MB,\n                     help=f"Free-space safety margin to keep on each headset (default {DEFAULT_MIN_FREE_MB} MB)")\n    ap.add_argument("--skip-power-config", action="store_true",\n                     help="Don\'t push even the WiFi never-sleep settings to each device before syncing "\n                          "(these normally apply regardless of --keep-screen-on, and are what actually "\n                          "prevents a headset dropping off ADB during a long sync or idle period)")\n    ap.add_argument("--keep-screen-on", action="store_true",\n                     help="Also force each headset\'s screen to stay on while charging (disables the idle "\n                          "screen timeout, \'stay awake while charging\', and the proximity auto-standby "\n                          "broadcasts). Off by default -- not needed for ADB connectivity (the WiFi "\n                          "never-sleep settings above already cover that regardless of screen state), and "\n                          "forcing the screen on can draw more power than some chargers can actually "\n                          "supply, net-draining a headset that appears to be charging. Only turn this on "\n                          "if you specifically want a headset visibly active during a sync and know the "\n                          "charger can handle it.")\n    ap.add_argument("--clean-stale-metadata", action="store_true",\n                     help="Detect and blank stale files/v3.local entries (claims a download exists but "\n                          "the file doesn\'t) -- safe, backs up on-device before writing, never touches "\n                          "entries whose file actually exists. Needs the app\'s package, from --package "\n                          "or derived from --remote-target. Runs even if the device is otherwise "\n                          "already up to date.")\n    ap.add_argument("--check-catalog-ids", action="store_true",\n                     help="Warn (doesn\'t block) about local content-ID folders that don\'t match any "\n                          "Video/Media ID in the app\'s own catalog -- those would get pushed but never "\n                          "shown or played, since the app is driven by its catalog, not by what\'s "\n                          "physically on disk. Needs the app\'s package, from --package or derived from "\n                          "--remote-target.")\n    ap.add_argument("--skip-install-registration", action="store_true",\n                     help="Don\'t update files/v3.local to mark freshly-pushed video/media content as "\n                          "installed. On by default: content pushed directly by this tool bypasses "\n                          "Headjack\'s own downloader, which is normally what writes that record, so "\n                          "without it the app (and anything it reports upstream about what a headset "\n                          "has installed) may not recognize newly-synced content even though the file "\n                          "is present and plays fine. Only ever fills in a previously-empty entry for "\n                          "content this run just pushed and verified -- never touches an entry that\'s "\n                          "already marked installed. Needs the app\'s package, from --package or derived "\n                          "from --remote-target.")\n    ap.add_argument("--keepalive", action="store_true",\n                     help="Run as a standalone watchdog: periodically wake known devices instead of syncing content")\n    ap.add_argument("--interval", type=int, default=DEFAULT_KEEPALIVE_INTERVAL,\n                     help=f"Seconds between keepalive wake pulses (default {DEFAULT_KEEPALIVE_INTERVAL})")\n    ap.add_argument("--parent-pid", type=int, default=None,\n                     help="If given, self-terminate when this process is no longer running "\n                          "(used by --keepalive so an orphaned watchdog can\'t outlive its launcher)")\n    ap.add_argument("--diagnose-bandwidth", action="store_true",\n                     help="Run a network bottleneck diagnostic instead of syncing content: checks the "\n                          "operator laptop\'s own network link, a single-device baseline push rate, a "\n                          "concurrency scaling test across multiple headsets (up to --workers), and "\n                          "per-headset WiFi link quality, then reports whether throughput is limited by "\n                          "a shared ceiling or has room to grow with more concurrency. Uses a generated "\n                          "random test file -- doesn\'t touch your actual content. Doesn\'t need "\n                          "--content-dir.")\n    ap.add_argument("--diagnose-file-size-mb", type=int, default=300,\n                     help="Size in MB of the random test file used for --diagnose-bandwidth (default 300)")\n    args = ap.parse_args()\n\n    if args.keepalive:\n        run_keepalive(args)\n        return\n\n    if args.diagnose_bandwidth:\n        run_bandwidth_diagnostic(args)\n        return\n\n    if not args.content_dir:\n        print("ERROR: --content-dir is required (unless using --keepalive or --diagnose-bandwidth)",\n              file=sys.stderr)\n        sys.exit(2)\n\n    content_dir = Path(args.content_dir).resolve()\n    if not content_dir.is_dir():\n        print(f"ERROR: content dir not found: {content_dir}", file=sys.stderr)\n        sys.exit(2)\n\n    if args.content_is_app_root and not args.package and not args.remote_target:\n        print("ERROR: --content-is-app-root needs --package (to derive the on-device app root) "\n              "unless --remote-target is also given explicitly", file=sys.stderr)\n        sys.exit(2)\n\n    if args.content_is_app_root and args.remote_target:\n        rt_normalized = args.remote_target.rstrip("/")\n        if rt_normalized.endswith("/files/Video") or rt_normalized.endswith("/files/Media") or \\\n                rt_normalized in ("files/Video", "files/Media"):\n            print("ERROR: --content-is-app-root is set but --remote-target "\n                  f"({args.remote_target!r}) looks like it still points at files/Video or "\n                  "files/Media specifically, not the app\'s root folder. With both set this way, "\n                  "content would be pushed one level too deep (.../files/Video/files/Video/...) "\n                  "and --prune would see the real existing content as \\"extra\\" and delete it. "\n                  "Either uncheck content-is-app-root, or point --remote-target at the app\'s root "\n                  "(e.g. /sdcard/Android/data/<package>) or leave it blank and pass --package "\n                  "instead.", file=sys.stderr)\n            sys.exit(2)\n\n    if args.remote_target:\n        remote_target = args.remote_target\n    elif args.content_is_app_root:\n        # content_dir IS the app\'s root (matching the on-device layout) --\n        # so the remote target is the app\'s root too, not files/Video\n        # specifically, since scan_subdirs below preserves the "files/Video/"\n        # and "files/Media/" prefixes in every relative path.\n        remote_target = f"/sdcard/Android/data/{args.package}"\n    elif args.package:\n        # /sdcard/Android/data/<package>/files/Video is where Headjack\n        # actually reads video content from (confirmed on a live device --\n        # each video lives at files/Video/<content-id>/<any-filename>,\n        # matched by folder ID, not the bare app data root). Still just a\n        # fallback -- pass --remote-target explicitly to override.\n        remote_target = f"/sdcard/Android/data/{args.package}/files/Video"\n    else:\n        print("ERROR: must pass --package or --remote-target", file=sys.stderr)\n        sys.exit(2)\n\n    state_dir = Path(args.state_dir)\n    state_dir.mkdir(parents=True, exist_ok=True)\n    log = Log(state_dir / "logs" / f"{datetime.now():%Y%m%d_%H%M%S}.log")\n\n    log.line(f"content_dir={content_dir} remote_target={remote_target} workers={args.workers} "\n              f"verify={args.verify} verify_hash={args.verify_hash} prune={args.prune} dry_run={args.dry_run} "\n              f"clean_stale_metadata={args.clean_stale_metadata} check_catalog_ids={args.check_catalog_ids} "\n              f"skip_install_registration={args.skip_install_registration} "\n              f"content_is_app_root={args.content_is_app_root}")\n\n    # optional: reconnect known wireless headsets that may have dropped off entirely\n    if args.connect_file:\n        for line in Path(args.connect_file).read_text().splitlines():\n            hp = line.strip()\n            if hp and not hp.startswith("#"):\n                adb_connect(hp, log)\n        time.sleep(2)\n\n    scan_subdirs = ["files/Video", "files/Media"] if args.content_is_app_root else None\n    local_manifest = build_local_manifest(content_dir, state_dir / "local_manifest_cache.json", log,\n                                           scan_subdirs=scan_subdirs)\n    if not local_manifest:\n        log.line("no local files found — nothing to sync")\n        sys.exit(0)\n    total_bytes = sum(v["size"] for v in local_manifest.values())\n    log.line(f"local content: {len(local_manifest)} files, {total_bytes / 1_073_741_824:.2f} GB")\n\n    protected_files = [rel for rel in local_manifest if is_protected_headjack_file(rel)]\n    if protected_files:\n        log.line(f"{len(protected_files)} local file(s) match Headjack\'s own device-specific "\n                  f"bookkeeping (v3.local, shader cache, manifests, etc.) and are excluded from "\n                  f"every device\'s push -- per-device state, not shared content. This usually "\n                  f"means --content-dir points at a full device clone rather than curated "\n                  f"content, worth fixing at the source.")\n        log.line("  e.g. " + ", ".join(protected_files[:8])\n                  + (f" (+{len(protected_files) - 8} more)" if len(protected_files) > 8 else ""))\n\n    devices = adb_devices()\n    ready = [s for s, st in devices.items() if st == "device"]\n    not_ready = {s: st for s, st in devices.items() if st != "device"}\n    for s, st in not_ready.items():\n        log.line(f"skipping (state={st})", s)\n\n    if args.devices:\n        allow = set(x.strip() for x in args.devices.split(","))\n        ready = [s for s in ready if s in allow]\n\n    if not ready:\n        log.line("no ready devices found")\n        sys.exit(1)\n\n    log.line(f"{len(ready)} device(s) ready: {\', \'.join(ready)}")\n    log.blank()\n\n    results = []\n    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:\n        futures = {\n            pool.submit(sync_device, s, local_manifest, content_dir, remote_target,\n                        state_dir, args, log): s\n            for s in ready\n        }\n        for fut in concurrent.futures.as_completed(futures):\n            s = futures[fut]\n            try:\n                results.append(fut.result())\n            except Exception as e:\n                log.line(f"CRASHED: {e}", s)\n                results.append({"device": s, "pushed": 0, "failed": -1, "skipped_all": False,\n                                 "deleted": 0, "failed_files": [], "error": str(e)})\n\n    # --- summary ---\n    log.blank()\n    log.line("=" * 70)\n    log.line("SUMMARY")\n    log.line("=" * 70)\n    up_to_date = sum(1 for r in results if r["skipped_all"])\n    had_failures = [r for r in results if r["failed"]]\n    unreachable = [r for r in results if r.get("error") == "unreachable"]\n    scan_failed = [r for r in results if r.get("error") == "remote_scan_failed"]\n    low_storage = [r for r in results if r.get("skipped_low_storage")]\n    total_pushed = sum(r["pushed"] for r in results)\n    total_stale_cleaned = sum(len(r.get("stale_v3local_cleaned", [])) for r in results)\n    total_registered = sum(len(r.get("v3local_registered", [])) for r in results)\n\n    for r in sorted(results, key=lambda r: r["device"]):\n        status = "UNREACHABLE" if r.get("error") == "unreachable" else \\\n                 "SCAN-FAILED" if r.get("error") == "remote_scan_failed" else \\\n                 "UP-TO-DATE" if r["skipped_all"] else \\\n                 ("OK" if not r["failed"] else "FAILURES")\n        extra = f" low_storage_skips={len(r[\'skipped_low_storage\'])}" if r.get("skipped_low_storage") else ""\n        if r.get("stale_v3local_cleaned"):\n            extra += f" stale_metadata_cleaned={len(r[\'stale_v3local_cleaned\'])}"\n        if r.get("v3local_registered"):\n            extra += f" v3local_registered={len(r[\'v3local_registered\'])}"\n        if r.get("reserved_space_suspected"):\n            extra += " REBOOT-SUGGESTED(space held by failed push)"\n        log.line(f"{r[\'device\']:<24} {status:<12} pushed={r[\'pushed\']} failed={r[\'failed\']} "\n                  f"deleted={r[\'deleted\']}{extra}")\n\n    log.line("-" * 70)\n    log.line(f"devices ready: {len(ready)} | up-to-date: {up_to_date} | "\n              f"unreachable: {len(unreachable)} | scan failed: {len(scan_failed)} | "\n              f"with failures: {len(had_failures)} | "\n              f"low on storage: {len(low_storage)} | total files pushed: {total_pushed}"\n              + (f" | stale metadata entries cleaned: {total_stale_cleaned}" if args.clean_stale_metadata else "")\n              + (f" | v3local entries registered: {total_registered}" if total_registered else ""))\n\n    reserved = sorted(r["device"] for r in results if r.get("reserved_space_suspected"))\n    other_low = [r["device"] for r in low_storage if r["device"] not in reserved]\n    if scan_failed or reserved or other_low:\n        log.blank()\n    if scan_failed:\n        log.line("WARNING: could not determine actual on-device state for some headsets (scan timed "\n                  "out or failed) -- they were SKIPPED this run rather than risk an unnecessary full "\n                  "re-push. Re-run to retry, or use --verify-hash only if you suspect a size collision "\n                  "specifically (much slower, more likely to time out on large content).")\n    if reserved:\n        log.line(f"WARNING: {len(reserved)} headset(s) likely have storage still held by an earlier "\n                  f"failed push (space used, but no file visible to overwrite): {\', \'.join(reserved)} "\n                  f"-- REBOOT these headsets and re-run before deleting any content")\n    if other_low:\n        log.line("WARNING: some headsets skipped updates due to low storage — "\n                  "see per-device logs, consider --prune or freeing space, then re-run")\n\n    report_path = state_dir / "logs" / "last_run_report.json"\n    report_path.write_text(json.dumps({"timestamp": now_iso(), "results": results}, indent=2))\n    log.close()\n\n    if had_failures or unreachable or low_storage:\n        sys.exit(1)\n    sys.exit(0)\n\n\nif __name__ == "__main__":\n    main()\n',
    'delete_video.py': '#!/usr/bin/env python3\n"""\nCXVR delete_video.py\n\nRemoves one or more specific videos\' content-ID folders from one or more headsets, and keeps\nfiles/v3.local consistent afterward by clearing that ID\'s "installed" marker -- otherwise\nHeadjack would keep reporting a video as installed after its files are gone. Also drops the\ndeleted rel path(s) from sync_files.py\'s own trusted-state cache for that device, so a later\nPLAIN sync (no --verify) correctly notices the file is missing and re-pushes it from the source\nfolder, rather than assuming it\'s still there.\n\nThis is a companion to sync_files.py and deliberately reuses its adb/v3.local/state helpers\ndirectly (materialize_scripts() in the control panel writes every embedded script into the same\ndirectory, so `import sync_files` works exactly like importing any other sibling module).\n\nUsage:\n    delete_video.py --video-ids ID1,ID2 --devices SERIAL1,SERIAL2 --remote-target PATH [options]\n    delete_video.py --video-ids ID1 --devices ALL --remote-target PATH --dry-run\n\n--devices ALL operates on every currently-connected, ready ("device" state) headset.\n"""\nimport argparse\nimport json\nimport os\nimport shlex\nimport sys\nimport tempfile\nfrom datetime import datetime\nfrom pathlib import Path\n\nimport sync_files as sf\n\n\ndef find_video_folder(serial: str, remote_target: str, video_id: str):\n    """sync_files.py\'s own remote_target can point at either the app\'s root or at files/Video\n    directly, depending on how it was invoked -- and a person\'s saved settings don\'t always say\n    which. Rather than guess from a flag here too, check the device for both candidate paths and\n    act on whichever one actually exists. Returns the list of candidates that exist (normally\n    zero or one; more than one is a genuine ambiguity worth surfacing rather than guessing)."""\n    app_root_style = str(Path(remote_target, "files", "Video", video_id))\n    direct_style = str(Path(remote_target, video_id))\n    candidates = [app_root_style] if app_root_style == direct_style else [app_root_style, direct_style]\n    found = []\n    for c in candidates:\n        res = sf.shell(serial, f"test -d {shlex.quote(c)} && echo YES", timeout=15)\n        if (res.stdout or "").strip() == "YES":\n            found.append(c)\n    return found\n\n\ndef folder_size_bytes(serial: str, path: str):\n    """Best-effort total size of a directory, for confirmation/dry-run display only -- returns\n    None if it can\'t be determined, which callers should treat as "unknown", not zero."""\n    res = sf.shell(serial, f"du -sk {shlex.quote(path)} 2>/dev/null", timeout=30)\n    if res.returncode != 0 or not (res.stdout or "").strip():\n        return None\n    try:\n        return int(res.stdout.split()[0]) * 1024\n    except (ValueError, IndexError):\n        return None\n\n\ndef unregister_in_v3local(serial: str, package: str, video_ids: list, dry_run: bool, log: sf.Log):\n    """Clears (blanks, never removes) the "v" entry for each given content ID in files/v3.local\n    -- the exact opposite of register_pushed_content_in_v3local() in sync_files.py, and built to\n    mirror its same read/validate/backup/write approach. Blanking rather than removing the ID\n    matches how Headjack\'s own downloader behaves when it forgets a download: the ID stays known,\n    just not marked installed. Returns {"skipped": str|None, "cleared": [id, ...]}."""\n    result = {"skipped": None, "cleared": []}\n    if not video_ids:\n        return result\n\n    v3local_path = f"/sdcard/Android/data/{package}/files/v3.local"\n    res = sf.shell(serial, f"cat {shlex.quote(v3local_path)}", timeout=15)\n    if res.returncode != 0 or not (res.stdout or "").strip():\n        result["skipped"] = "v3.local not found or empty on this device"\n        return result\n\n    raw = res.stdout\n    had_bom = raw.startswith("\\ufeff")\n    if had_bom:\n        raw = raw[1:]\n\n    try:\n        data = json.loads(raw)\n    except json.JSONDecodeError as e:\n        result["skipped"] = f"v3.local did not parse as JSON ({e}) -- leaving it untouched"\n        return result\n\n    if not (isinstance(data, dict) and isinstance(data.get("c"), list)\n            and isinstance(data.get("v"), list) and len(data["c"]) == len(data["v"])):\n        result["skipped"] = ("v3.local structure didn\'t match the expected {c:[...], v:[...]} "\n                              "shape -- leaving it untouched")\n        return result\n\n    ids, filenames = list(data["c"]), list(data["v"])\n    for video_id in video_ids:\n        for i, cid in enumerate(ids):\n            if cid == video_id and filenames[i]:\n                filenames[i] = ""\n                result["cleared"].append(video_id)\n\n    if not result["cleared"]:\n        return result\n\n    if dry_run:\n        log.line(f"[dry-run] would clear v3.local install marker for: {\', \'.join(result[\'cleared\'])}",\n                  serial)\n        result["cleared"] = []\n        return result\n\n    fixed_data = dict(data)\n    fixed_data["c"] = ids\n    fixed_data["v"] = filenames\n    new_content = json.dumps(fixed_data, indent=4)\n    if had_bom:\n        new_content = "\\ufeff" + new_content\n    json.loads(new_content.lstrip("\\ufeff"))\n\n    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")\n    backup_path = f"{v3local_path}.bak.{timestamp}"\n    sf.shell(serial, f"cp {shlex.quote(v3local_path)} {shlex.quote(backup_path)}", timeout=15)\n\n    with tempfile.NamedTemporaryFile(mode="w", suffix=".local", delete=False, encoding="utf-8") as tf:\n        tf.write(new_content)\n        tmp_path = tf.name\n    try:\n        push_res = sf.run_adb(["-s", serial, "push", tmp_path, v3local_path], timeout=30)\n        if push_res.returncode != 0:\n            log.line(f"failed to push updated v3.local: {(push_res.stderr or \'\').strip()[:200]}", serial)\n            result["cleared"] = []\n            return result\n    finally:\n        os.unlink(tmp_path)\n\n    log.line(f"cleared v3.local install marker (backup: {backup_path}) for: "\n              f"{\', \'.join(result[\'cleared\'])}", serial)\n    return result\n\n\ndef rel_belongs_to_video(rel: str, video_id: str) -> bool:\n    """True if a trusted-state rel path is under this video\'s content-ID folder -- matches\n    either the app-root-style \'files/Video/<id>/<filename>\' or a content_dir pointed directly\n    at just the video folder (\'<id>/<filename>\'), mirroring the flexibility sync_files.py itself\n    allows for remote_target."""\n    parts = Path(rel).parts\n    if video_id not in parts:\n        return False\n    idx = parts.index(video_id)\n    return idx == 0 or parts[idx - 1] == "Video"\n\n\ndef prune_from_trusted_state(state_dir: Path, serial: str, video_ids: list, dry_run: bool, log: sf.Log):\n    """Drops any trusted-state manifest entries under the given video IDs for this device, so a\n    later PLAIN sync (no --verify) correctly notices the file is gone and re-pushes it from the\n    source folder if it\'s still there, instead of trusting a now-stale cached record that thinks\n    everything already matches."""\n    state = sf.load_device_state(state_dir, serial)\n    if not state or not isinstance(state.get("manifest"), dict):\n        return\n    manifest = state["manifest"]\n    to_drop = [rel for rel in manifest if any(rel_belongs_to_video(rel, vid) for vid in video_ids)]\n    if not to_drop:\n        return\n    if dry_run:\n        log.line(f"[dry-run] would drop {len(to_drop)} entry(ies) from this device\'s trusted-state "\n                  f"cache so a future plain sync re-checks: {\', \'.join(to_drop)}", serial)\n        return\n    for rel in to_drop:\n        del manifest[rel]\n    sf.save_device_state(state_dir, serial, manifest)\n    log.line(f"dropped {len(to_drop)} entry(ies) from this device\'s trusted-state cache: "\n              f"{\', \'.join(to_drop)}", serial)\n\n\ndef delete_video_from_device(serial: str, remote_target: str, package: str, video_ids: list,\n                              state_dir: Path, dry_run: bool, skip_v3local_update: bool, log: sf.Log):\n    result = {"device": serial, "deleted": [], "not_found": [], "ambiguous": [], "error": None}\n\n    if not sf.device_alive(serial):\n        result["error"] = "unreachable"\n        log.line("device unreachable, skipping", serial)\n        return result\n\n    for video_id in video_ids:\n        found = find_video_folder(serial, remote_target, video_id)\n        if len(found) == 0:\n            result["not_found"].append(video_id)\n            log.line(f"no folder found for {video_id} on this device -- may already be deleted, "\n                      f"or never existed here", serial)\n            continue\n        if len(found) > 1:\n            result["ambiguous"].append(video_id)\n            log.line(f"AMBIGUOUS: found {video_id} at more than one path on this device "\n                      f"({\', \'.join(found)}) -- skipping rather than guess which is real", serial)\n            continue\n\n        path = found[0]\n        size_bytes = folder_size_bytes(serial, path)\n        size_str = f"{size_bytes / 1_048_576:.1f} MB" if size_bytes is not None else "unknown size"\n\n        if dry_run:\n            log.line(f"[dry-run] would delete {path} ({size_str})", serial)\n            continue\n\n        res = sf.shell(serial, f"rm -rf {shlex.quote(path)}", timeout=60)\n        if res.returncode == 0:\n            result["deleted"].append(video_id)\n            log.line(f"deleted {path} ({size_str})", serial)\n        else:\n            result["error"] = "delete_failed"\n            log.line(f"FAILED to delete {path}: {(res.stderr or \'\').strip()[:200]}", serial)\n\n    if not skip_v3local_update:\n        ids_to_clear = video_ids if dry_run else result["deleted"]\n        if ids_to_clear and package:\n            unregister_in_v3local(serial, package, ids_to_clear, dry_run, log)\n        elif ids_to_clear and not package:\n            log.line("could not determine the app\'s package (neither --package nor derivable "\n                      "from --remote-target) -- skipping v3.local cleanup", serial)\n\n    ids_for_state = video_ids if dry_run else result["deleted"]\n    if ids_for_state:\n        prune_from_trusted_state(state_dir, serial, ids_for_state, dry_run, log)\n\n    return result\n\n\ndef main():\n    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)\n    ap.add_argument("--video-ids", required=True,\n                     help="Comma-separated content-ID folder names to delete, e.g. "\n                          "871t867donz61pdcs4ewanukhh7ajmk3,zhv9bh2y8ee6z662kcd3y7vcel85xq7u")\n    ap.add_argument("--devices", required=True,\n                     help="Comma-separated device serials, or ALL for every currently-connected, "\n                          "ready headset")\n    ap.add_argument("--remote-target", required=True,\n                     help="Same value used for the sync -- either the app\'s root or files/Video "\n                          "directly; this tool checks the device to figure out which")\n    ap.add_argument("--package", help="App package -- optional if derivable from --remote-target, "\n                                       "needed to locate files/v3.local for bookkeeping cleanup")\n    ap.add_argument("--skip-v3local-update", action="store_true",\n                     help="Don\'t clear the v3.local install marker after deleting -- off by "\n                          "default, since leaving it set would make Headjack keep reporting "\n                          "deleted content as installed")\n    ap.add_argument("--state-dir", default=str(sf.DEFAULT_STATE_DIR),\n                     help="Same state folder used by sync_files.py, so trusted-state cleanup lines up")\n    ap.add_argument("--dry-run", action="store_true")\n    args = ap.parse_args()\n\n    video_ids = [v.strip() for v in args.video_ids.split(",") if v.strip()]\n    if not video_ids:\n        print("ERROR: --video-ids produced no IDs", file=sys.stderr)\n        sys.exit(2)\n\n    effective_package = args.package or sf.derive_package_from_remote_path(args.remote_target)\n\n    state_dir = Path(args.state_dir)\n    state_dir.mkdir(parents=True, exist_ok=True)\n    log = sf.Log(state_dir / "logs" / f"delete_{datetime.now():%Y%m%d_%H%M%S}.log")\n    log.line(f"video_ids={video_ids} remote_target={args.remote_target} package={effective_package} "\n              f"dry_run={args.dry_run} skip_v3local_update={args.skip_v3local_update}")\n\n    if args.devices.strip().upper() == "ALL":\n        all_devices = sf.adb_devices()\n        target_serials = [s for s, st in all_devices.items() if st == "device"]\n        if not target_serials:\n            log.line("no ready devices found")\n            sys.exit(1)\n    else:\n        target_serials = [s.strip() for s in args.devices.split(",") if s.strip()]\n\n    log.line(f"{len(target_serials)} device(s) targeted: {\', \'.join(target_serials)}")\n    log.blank()\n\n    results = []\n    for serial in target_serials:\n        results.append(delete_video_from_device(\n            serial, args.remote_target, effective_package, video_ids,\n            state_dir, args.dry_run, args.skip_v3local_update, log))\n\n    log.blank()\n    log.line("=" * 70)\n    log.line("SUMMARY" + (" (DRY RUN -- nothing was actually changed)" if args.dry_run else ""))\n    log.line("=" * 70)\n    any_error = False\n    for r in results:\n        if r["error"] == "unreachable":\n            log.line(f"{r[\'device\']:<24} UNREACHABLE")\n            any_error = True\n        else:\n            bits = []\n            if r["deleted"]:\n                bits.append(f"deleted={len(r[\'deleted\'])}")\n            if r["not_found"]:\n                bits.append(f"not_found={len(r[\'not_found\'])}")\n            if r["ambiguous"]:\n                bits.append(f"ambiguous={len(r[\'ambiguous\'])}")\n                any_error = True\n            if r["error"] == "delete_failed":\n                bits.append("DELETE FAILED")\n                any_error = True\n            log.line(f"{r[\'device\']:<24} {\' \'.join(bits) if bits else \'nothing to do\'}")\n\n    log.close()\n    sys.exit(1 if any_error else 0)\n\n\nif __name__ == "__main__":\n    main()\n',
    'captureDiagnostics.sh': '#!/bin/bash\n# Usage: captureDiagnostics.sh [--device SERIAL] [--repeat N] [--interval SECONDS]\n#                              [--out-dir DIR] [--no-screencap]\n#\n# Takes a READ-ONLY diagnostic snapshot of one headset (or every connected\n# headset if --device is omitted) and writes it to a timestamped folder. Sends\n# no input, changes no settings, starts nothing -- it only reads state.\n#\n# The point of this tool is to capture what a fault ACTUALLY looks like, so\n# detection for it can be built from evidence instead of assumption. Two open\n# questions it exists to answer:\n#\n#   1. The overheat prompt: does it take window focus (visible in\n#      mCurrentFocus/mFocusedApp), is it a non-focusable overlay (visible only\n#      in the full window list), or is it a compositor layer that only shows up\n#      in SurfaceFlinger/logcat? popupWatchdog.sh\'s existing focus-based check\n#      only catches the first case, and its own header flags that as unverified.\n#\n#   2. The mid-playback black screen: is the display actually POWERED OFF\n#      (unambiguous -- normal between-film black frames happen with the display\n#      ON), or is the display on while the app renders black? Those are\n#      different faults needing different detection and different recovery.\n#\n# --repeat/--interval exist because a transient dialog is easy to miss by a few\n# seconds. Capturing a short burst means the operator doesn\'t have to hit the\n# button at exactly the right moment.\n#\n# Screencap is included because seeing the actual frame is worth a lot when\n# interpreting everything else -- but it\'s the slowest part, so --no-screencap\n# is offered for repeat bursts over a busy network.\n\nDEVICE=""\nREPEAT=1\nINTERVAL=5\nOUT_DIR="$HOME/.cxvr_control_panel/snapshots"\nDO_SCREENCAP=1\n\nwhile [ $# -gt 0 ]; do\n    case "$1" in\n        --device) DEVICE="$2"; shift 2 ;;\n        --repeat) REPEAT="$2"; shift 2 ;;\n        --interval) INTERVAL="$2"; shift 2 ;;\n        --out-dir) OUT_DIR="$2"; shift 2 ;;\n        --no-screencap) DO_SCREENCAP=0; shift ;;\n        *) shift ;;\n    esac\ndone\n\nif [ -n "$DEVICE" ]; then\n    devices="$DEVICE"\nelse\n    devices=$(adb devices | awk \'NR>1 && $2=="device" {print $1}\')\nfi\n\nif [ -z "$devices" ]; then\n    echo "captureDiagnostics: no connected devices found" >&2\n    exit 1\nfi\n\n# One dump, one file. Each is wrapped in `timeout` because a headset in a bad\n# state is exactly the situation where a dumpsys call can hang, and a capture\n# tool that hangs during a fault is useless.\ncapture_one() {\n    local d="$1" dest="$2"\n    mkdir -p "$dest"\n\n    {\n        echo "device: $d"\n        echo "captured: $(date -Iseconds)"\n        echo "host: $(hostname 2>/dev/null)"\n    } > "$dest/capture_info.txt"\n\n    # Cheap identity/version info first -- tells us which dumpsys output\n    # formats to expect when interpreting everything below.\n    timeout 15 adb -s "$d" shell getprop > "$dest/getprop.txt" 2>&1\n\n    # --- the black-screen question ---\n    # Display Power: state=ON|OFF plus mScreenOn/mWakefulness live here.\n    timeout 20 adb -s "$d" shell dumpsys power > "$dest/dumpsys_power.txt" 2>&1\n    timeout 20 adb -s "$d" shell dumpsys display > "$dest/dumpsys_display.txt" 2>&1\n\n    # --- the overheat question ---\n    # FULL window list, not just the focused lines: an overlay that never takes\n    # focus is invisible to a focus-only grep, which is a live hypothesis for\n    # why the existing watchdog may miss this prompt.\n    timeout 20 adb -s "$d" shell dumpsys window windows > "$dest/dumpsys_window_windows.txt" 2>&1\n    timeout 20 adb -s "$d" shell dumpsys activity activities > "$dest/dumpsys_activity_activities.txt" 2>&1\n\n    # --- is anything actually still playing? ---\n    timeout 20 adb -s "$d" shell dumpsys media_session > "$dest/dumpsys_media_session.txt" 2>&1\n    timeout 20 adb -s "$d" shell dumpsys audio > "$dest/dumpsys_audio.txt" 2>&1\n\n    # --- is anything still being rendered? ---\n    # A black frame between films is still a PRESENTED frame; a stalled\n    # renderer stops presenting. The layer list makes it possible to pick the\n    # right layer for --latency later.\n    timeout 25 adb -s "$d" shell dumpsys SurfaceFlinger > "$dest/dumpsys_surfaceflinger.txt" 2>&1\n    timeout 15 adb -s "$d" shell dumpsys SurfaceFlinger --list > "$dest/surfaceflinger_layers.txt" 2>&1\n\n    # --- thermal ---\n    timeout 15 adb -s "$d" shell dumpsys thermalservice > "$dest/dumpsys_thermalservice.txt" 2>&1\n    timeout 15 adb -s "$d" shell dumpsys battery > "$dest/dumpsys_battery.txt" 2>&1\n\n    # --- recent log ring buffer: decoder errors, thermal warnings, app crashes ---\n    timeout 25 adb -s "$d" logcat -d -t 2000 > "$dest/logcat_tail.txt" 2>&1\n\n    if [ "$DO_SCREENCAP" = "1" ]; then\n        timeout 30 adb -s "$d" exec-out screencap -p > "$dest/screen.png" 2>/dev/null\n        # exec-out isn\'t available on every build; fall back to the\n        # write-then-pull route rather than silently leaving a 0-byte file.\n        if [ ! -s "$dest/screen.png" ]; then\n            rm -f "$dest/screen.png"\n            if timeout 30 adb -s "$d" shell screencap -p /sdcard/_cxvr_snap.png 2>/dev/null; then\n                timeout 30 adb -s "$d" pull /sdcard/_cxvr_snap.png "$dest/screen.png" >/dev/null 2>&1\n                timeout 15 adb -s "$d" shell rm -f /sdcard/_cxvr_snap.png >/dev/null 2>&1\n            fi\n        fi\n    fi\n\n    # A short human-readable digest so the interesting lines are visible\n    # without opening eight files.\n    {\n        echo "=== display power ==="\n        grep -E "Display Power|mScreenOn|mWakefulness|mHolding" "$dest/dumpsys_power.txt" 2>/dev/null | head -20\n        echo\n        echo "=== focused window / app ==="\n        grep -E "mCurrentFocus|mFocusedApp|mFocusedWindow" "$dest/dumpsys_window_windows.txt" 2>/dev/null | head -10\n        echo\n        echo "=== windows mentioning thermal/overheat/temperature ==="\n        grep -iE "thermal|overheat|temperature|too hot|cooling" "$dest/dumpsys_window_windows.txt" 2>/dev/null | head -20\n        echo\n        echo "=== logcat lines mentioning thermal/overheat ==="\n        grep -iE "thermal|overheat|too hot|temperature" "$dest/logcat_tail.txt" 2>/dev/null | tail -30\n        echo\n        echo "=== battery/thermal summary ==="\n        grep -iE "temperature|level|status" "$dest/dumpsys_battery.txt" 2>/dev/null | head -10\n    } > "$dest/SUMMARY.txt" 2>/dev/null\n\n    echo "  saved: $dest"\n}\n\nstamp=$(date +%Y%m%d_%H%M%S)\nfor i in $(seq 1 "$REPEAT"); do\n    for d in $devices; do\n        safe_name=$(echo "$d" | tr -c \'a-zA-Z0-9\' \'_\')\n        if [ "$REPEAT" -gt 1 ]; then\n            dest="$OUT_DIR/${safe_name}_${stamp}/pass_$(printf \'%02d\' "$i")"\n        else\n            dest="$OUT_DIR/${safe_name}_${stamp}"\n        fi\n        echo "[$d] capturing (pass $i/$REPEAT)..."\n        capture_one "$d" "$dest" &\n    done\n    wait\n    if [ "$i" -lt "$REPEAT" ]; then\n        sleep "$INTERVAL"\n    fi\ndone\n\necho\necho "Done. Snapshots are under: $OUT_DIR"\necho "Start with SUMMARY.txt in each folder -- it digests the lines that matter"\necho "for the black-screen and overheat questions."\n',
    'overheatWatchdog.py': '#!/usr/bin/env python3\n"""\nCXVR overheatWatchdog.py\n\nWatches every connected headset for the Oculus overheat prompt and, when armed,\ndismisses it by sending BACK.\n\nWHY BACK, AND WHY THIS IS A SEPARATE DAEMON FROM popupWatchdog.sh\n-----------------------------------------------------------------\nIn scrcpy, right-click sends BACK (keycode 4) and middle-click sends HOME\n(keycode 3). The operator reports that right-clicking dismisses the overheat\nprompt, so the dismissal key is BACK.\n\npopupWatchdog.sh sends HOME whenever the focused window ISN\'T the expected\npackage -- a deliberately blunt rule that\'s safe precisely because HOME is\nsafe: worst case it returns an already-fine headset to its own launcher.\n\nBACK is NOT safe that way. Inside the Headjack app, BACK plausibly exits\nplayback or walks the menu backwards, which during a show is worse than the\noverheat prompt itself. So this daemon must never use BACK as a general\n"something\'s wrong" fallback. It fires only on a POSITIVE match for the\noverheat prompt specifically, and does nothing at all otherwise. That\ndifference in safety model is why this is a sibling daemon rather than a flag\nadded to the existing, working popupWatchdog.sh.\n\nDETECTION IS DELIBERATELY CONFIGURABLE AND UNPROVEN\n---------------------------------------------------\nThe prompt\'s real signature on this hardware has not been captured yet. It\ncould be a focusable dialog, a non-focusable overlay, or a compositor layer.\nSo detection here is pattern-based over several sources, with the pattern\nexposed as a flag, and the daemon defaults to OBSERVE-ONLY: it logs what it\nwould have done and sends nothing until explicitly armed with --arm.\n\nUse captureDiagnostics.sh during a real overheat to find the true signature,\nthen narrow --match-pattern to it before arming. A broad default pattern is\nfine for observing and terrible for acting -- which is exactly why acting is\noff by default.\n\nUsage:\n    overheatWatchdog.py --package com.Example.App [--arm] [--interval 10]\n                        [--match-pattern REGEX] [--cooldown 60]\n                        [--state-dir DIR] [--parent-pid PID]\n"""\nimport argparse\nimport os\nimport re\nimport sys\nimport time\nfrom datetime import datetime\nfrom pathlib import Path\n\nimport sync_files as sf\n\n# Candidate signature for the overheat prompt. Deliberately broad: broad is\n# right for OBSERVING (we\'d rather log a few irrelevant windows than miss the\n# real one while characterizing it) and wrong for ACTING, which is why arming\n# is a separate, explicit step and this pattern should be narrowed first.\nDEFAULT_MATCH_PATTERN = r"thermal|overheat|too hot|temperature|cooling|heat"\n\nKEYCODE_BACK = 4\n\n\ndef sentinel_blocks_action(state_dir: Path):\n    """Returns a reason string if automated actions are currently suppressed,\n    else None. Two independent brakes, both simple files so they take effect\n    immediately without restarting any daemon:\n\n      show_mode        -- operator has disabled all automation during a\n                          performance; monitoring and logging continue.\n      sync_in_progress -- a content sync is running. A sync already manipulates\n                          power state and saturates the AP; injecting input\n                          mid-push risks exactly the interrupted-transfer\n                          situation this project spent a long time hardening\n                          against."""\n    if (state_dir / "show_mode").exists():\n        return "show mode is on"\n    if (state_dir / "sync_in_progress").exists():\n        return "a content sync is running"\n    return None\n\n\ndef gather_signals(serial: str, package: str):\n    """Reads the places the overheat prompt could plausibly show up. Returns a\n    dict of source -> matching text, or None for a source that couldn\'t be read\n    (which is NOT the same as \'nothing matched\' and must never be treated as\n    evidence of anything)."""\n    signals = {}\n\n    res = sf.shell(serial, "dumpsys window windows", timeout=20)\n    signals["windows"] = res.stdout if res.returncode == 0 and res.stdout else None\n\n    res = sf.shell(serial, "logcat -d -t 200", timeout=20)\n    signals["logcat"] = res.stdout if res.returncode == 0 and res.stdout else None\n\n    return signals\n\n\ndef find_matches(signals: dict, pattern: str, package: str):\n    """Returns (matched: bool, evidence: list[str], focus_line: str|None).\n\n    Only counts a line as evidence if it matches the pattern AND isn\'t part of\n    our own app\'s window/log noise -- a Headjack window whose title happens to\n    contain a matching word shouldn\'t look like an overheat prompt."""\n    rx = re.compile(pattern, re.IGNORECASE)\n    evidence = []\n    focus_line = None\n\n    windows = signals.get("windows")\n    if windows:\n        for line in windows.splitlines():\n            stripped = line.strip()\n            if ("mCurrentFocus" in stripped or "mFocusedApp" in stripped) and focus_line is None:\n                focus_line = stripped\n            if rx.search(stripped) and package not in stripped:\n                evidence.append(f"window: {stripped[:200]}")\n\n    logcat = signals.get("logcat")\n    if logcat:\n        for line in logcat.splitlines():\n            if rx.search(line):\n                evidence.append(f"logcat: {line.strip()[:200]}")\n\n    return (len(evidence) > 0), evidence, focus_line\n\n\ndef cooldown_ok(state_dir: Path, serial: str, cooldown: int) -> bool:\n    p = state_dir / f"overheat_attempt_{sf.sanitize(serial)}"\n    if not p.exists():\n        return True\n    try:\n        last = float(p.read_text().strip())\n    except (ValueError, OSError):\n        return True\n    return (time.time() - last) >= cooldown\n\n\ndef mark_attempt(state_dir: Path, serial: str):\n    (state_dir / f"overheat_attempt_{sf.sanitize(serial)}").write_text(str(time.time()))\n\n\ndef check_device(serial: str, args, state_dir: Path, log: sf.Log):\n    signals = gather_signals(serial, args.package)\n\n    if signals.get("windows") is None and signals.get("logcat") is None:\n        # Couldn\'t read anything at all this round -- device slow or dropped.\n        # Never act on missing information.\n        return\n\n    matched, evidence, focus_line = find_matches(signals, args.match_pattern, args.package)\n    if not matched:\n        return\n\n    head = evidence[0] if evidence else "(no evidence captured)"\n    extra = f" (+{len(evidence) - 1} more)" if len(evidence) > 1 else ""\n\n    if not args.arm:\n        log.line(f"[observe-only] overheat signature matched; would send BACK. "\n                  f"Evidence: {head}{extra}. Focus: {focus_line or \'unknown\'}", serial)\n        return\n\n    blocked = sentinel_blocks_action(state_dir)\n    if blocked:\n        log.line(f"overheat signature matched but action suppressed ({blocked}). "\n                  f"Evidence: {head}{extra}", serial)\n        return\n\n    if not cooldown_ok(state_dir, serial, args.cooldown):\n        return\n\n    mark_attempt(state_dir, serial)\n    log.line(f"overheat signature matched -- sending BACK to dismiss. "\n              f"Evidence: {head}{extra}. Focus: {focus_line or \'unknown\'}", serial)\n    sf.shell(serial, f"input keyevent {KEYCODE_BACK}", timeout=15)\n\n\ndef parent_alive(parent_pid):\n    if not parent_pid:\n        return True\n    try:\n        os.kill(int(parent_pid), 0)\n        return True\n    except (OSError, ValueError):\n        return False\n\n\ndef main():\n    ap = argparse.ArgumentParser(description=__doc__,\n                                  formatter_class=argparse.RawDescriptionHelpFormatter)\n    ap.add_argument("--package", required=True,\n                     help="The app that SHOULD be running -- used to avoid mistaking our own "\n                          "app\'s windows/log lines for the overheat prompt")\n    ap.add_argument("--arm", action="store_true",\n                     help="Actually send BACK on a match. Off by default: the daemon observes and "\n                          "logs what it would have done, so the signature can be validated against "\n                          "a real overheat before it\'s ever allowed to inject input")\n    ap.add_argument("--match-pattern", default=DEFAULT_MATCH_PATTERN,\n                     help="Regex identifying the overheat prompt. Narrow this to the real signature "\n                          "(from captureDiagnostics.sh output) before arming")\n    ap.add_argument("--interval", type=int, default=10)\n    ap.add_argument("--cooldown", type=int, default=60,\n                     help="Minimum seconds between BACK presses on the same headset")\n    ap.add_argument("--state-dir", default=str(Path.home() / ".cxvr_control_panel"))\n    ap.add_argument("--parent-pid")\n    args = ap.parse_args()\n\n    state_dir = Path(args.state_dir)\n    state_dir.mkdir(parents=True, exist_ok=True)\n    log_dir = state_dir / "logs"\n    log_dir.mkdir(parents=True, exist_ok=True)\n    log = sf.Log(log_dir / f"overheat_watchdog_{datetime.now():%Y%m%d_%H%M%S}.log")\n\n    mode = "ARMED (will send BACK on match)" if args.arm else "OBSERVE-ONLY (will not send anything)"\n    log.line(f"overheatWatchdog starting -- {mode}; interval={args.interval}s "\n              f"cooldown={args.cooldown}s pattern={args.match_pattern!r}")\n    if not args.arm:\n        log.line("Arm it only after confirming this pattern matches a REAL overheat prompt and "\n                  "nothing else -- see captureDiagnostics.sh.")\n\n    while True:\n        if not parent_alive(args.parent_pid):\n            log.line("parent process is gone -- exiting")\n            log.close()\n            return 0\n        try:\n            devices = [s for s, st in sf.adb_devices().items() if st == "device"]\n        except Exception as e:\n            log.line(f"could not enumerate devices: {e}")\n            devices = []\n        for serial in devices:\n            try:\n                check_device(serial, args, state_dir, log)\n            except Exception as e:\n                log.line(f"check failed: {e}", serial)\n        for _ in range(args.interval):\n            if not parent_alive(args.parent_pid):\n                log.line("parent process is gone -- exiting")\n                log.close()\n                return 0\n            time.sleep(1)\n\n\nif __name__ == "__main__":\n    sys.exit(main())\n',
    'blackScreenProbe.py': '#!/usr/bin/env python3\n"""\nCXVR blackScreenProbe.py\n\nSamples each headset\'s playback-related state on an interval, writes it to a\nper-device CSV, and -- only when explicitly armed -- recovers from the one\nblack-screen case that can be identified without guessing.\n\nTHE PROBLEM THIS IS SHAPED AROUND\n----------------------------------\nHeadsets sometimes go black mid-playback while still powered and streaming; a\nsleep->wake cycle fixes it. The cause isn\'t known yet. Naive black-frame\ndetection is unacceptable, because genuinely black frames occur between films,\nand a spurious sleep-cycle during a show is worse than the fault.\n\nThe way out is that "black screen" is probably two different faults:\n\n  Case A -- the display is actually POWERED OFF. `dumpsys power` reports\n    `Display Power: state=OFF` (with mScreenOn=/mWakefulness= as alternates on\n    other builds). This is UNAMBIGUOUS: normal between-film blackness happens\n    with the display ON. No pixel analysis, no confusion with a film\n    transition. Plausible cause on this hardware: the proximity sensor blanking\n    the display when it thinks the headset came off a head.\n\n  Case B -- display ON, app rendering black (decoder stall, app fault,\n    thermal). This is the one that looks like a film transition, and it is NOT\n    safe to act on from a single signal. A black frame between films is still a\n    PRESENTED frame, so frame presentation is the most promising discriminator\n    -- but the threshold that separates "long transition" from "stalled" has to\n    be MEASURED on this fleet, not guessed.\n\nSo: Case A recovery can be armed once observed to be correct. Case B is\ndeliberately DETECTION-ONLY here, no matter what flags are passed. What this\ntool produces for Case B is data -- rows covering both real faults and every\nnormal film transition -- which is what a future threshold should be chosen\nfrom.\n\nUsage:\n    blackScreenProbe.py --package com.Example.App [--interval 20]\n                        [--arm-display-off] [--consecutive 3]\n                        [--recovery wake|cycle] [--state-dir DIR]\n                        [--parent-pid PID]\n"""\nimport argparse\nimport csv\nimport os\nimport re\nimport sys\nimport time\nfrom datetime import datetime\nfrom pathlib import Path\n\nimport sync_files as sf\n\nKEYCODE_WAKEUP = 224\nKEYCODE_SLEEP = 223\n\nCSV_FIELDS = [\n    "timestamp", "device", "display_state", "wakefulness", "foreground_matches_app",\n    "focus", "audio_active", "battery_temp_c", "verdict", "note",\n]\n\n\ndef parse_display_state(power_dump: str):\n    """Returns (\'ON\'|\'OFF\'|\'DOZE\'|None, wakefulness|None) from `dumpsys power`.\n\n    Tries the field names in the order they\'re most likely to be authoritative\n    on this Android 7-era build, and returns None rather than a guess when\n    nothing matches -- an unrecognized dump format must never read as \'OFF\',\n    since OFF is the state that can trigger recovery."""\n    if not power_dump:\n        return None, None\n\n    display_state = None\n    m = re.search(r"Display Power:\\s*state=(\\w+)", power_dump)\n    if m:\n        display_state = m.group(1).upper()\n    else:\n        m = re.search(r"mScreenOn=(true|false)", power_dump, re.IGNORECASE)\n        if m:\n            display_state = "ON" if m.group(1).lower() == "true" else "OFF"\n\n    wakefulness = None\n    m = re.search(r"mWakefulness=(\\w+)", power_dump)\n    if m:\n        wakefulness = m.group(1)\n\n    return display_state, wakefulness\n\n\ndef parse_audio_active(audio_dump: str):\n    """Best-effort \'is anything playing\'. Returns True/False/None (None =\n    couldn\'t tell, which is treated as unknown, never as silence)."""\n    if not audio_dump:\n        return None\n    for pat in (r"state:\\s*started", r"State:\\s*STARTED", r"mState=STARTED"):\n        if re.search(pat, audio_dump):\n            return True\n    if re.search(r"players:", audio_dump, re.IGNORECASE):\n        return bool(re.search(r"state:\\s*(started|idle)", audio_dump, re.IGNORECASE)) and \\\n            bool(re.search(r"state:\\s*started", audio_dump, re.IGNORECASE))\n    return None\n\n\ndef parse_battery_temp(battery_dump: str):\n    """Battery temperature in Celsius (dumpsys reports tenths)."""\n    if not battery_dump:\n        return None\n    m = re.search(r"temperature:\\s*(-?\\d+)", battery_dump)\n    if not m:\n        return None\n    try:\n        return int(m.group(1)) / 10.0\n    except ValueError:\n        return None\n\n\ndef sample_device(serial: str, package: str):\n    """One read-only sampling pass. Every field may be None, meaning \'couldn\'t\n    determine\' -- callers must distinguish that from a real value."""\n    sample = {"device": serial, "timestamp": datetime.now().isoformat(timespec="seconds")}\n\n    res = sf.shell(serial, "dumpsys power", timeout=20)\n    power_dump = res.stdout if res.returncode == 0 else None\n    display_state, wakefulness = parse_display_state(power_dump)\n    sample["display_state"] = display_state\n    sample["wakefulness"] = wakefulness\n\n    res = sf.shell(serial, "dumpsys window windows | grep -E \'mCurrentFocus|mFocusedApp\'", timeout=20)\n    focus = res.stdout.strip() if res.returncode == 0 and res.stdout else None\n    sample["focus"] = (focus.splitlines()[0].strip()[:160] if focus else None)\n    sample["foreground_matches_app"] = (package in focus) if focus else None\n\n    res = sf.shell(serial, "dumpsys audio", timeout=20)\n    sample["audio_active"] = parse_audio_active(res.stdout if res.returncode == 0 else None)\n\n    res = sf.shell(serial, "dumpsys battery", timeout=15)\n    sample["battery_temp_c"] = parse_battery_temp(res.stdout if res.returncode == 0 else None)\n\n    return sample\n\n\ndef classify(sample: dict):\n    """Turns one sample into a verdict. Only two verdicts can ever be\n    actionable, and only one of them is unambiguous:\n\n      display_off_during_app -- Case A. Display genuinely off while our app is\n        in the foreground. Safe to act on because normal between-film blackness\n        happens with the display ON.\n      unknown_display_state  -- couldn\'t read the display state. Explicitly a\n        non-verdict; never actionable.\n      ok                     -- nothing to report.\n\n    Case B is NOT classified here on purpose. Detecting \'display on but\n    rendering black\' needs a frame-presentation threshold measured from this\n    tool\'s own output across real transitions; inventing one here would be the\n    exact guess this design is trying to avoid."""\n    if sample.get("display_state") is None:\n        return "unknown_display_state", "could not read display state -- not actionable"\n\n    if sample["display_state"] in ("OFF", "DOZE"):\n        if sample.get("foreground_matches_app") is True:\n            return ("display_off_during_app",\n                    f"display={sample[\'display_state\']} while the app is foreground")\n        if sample.get("foreground_matches_app") is None:\n            return ("unknown_display_state",\n                    f"display={sample[\'display_state\']} but foreground app unknown -- not actionable")\n        return ("display_off_other_app",\n                f"display={sample[\'display_state\']} but a different app is foreground")\n\n    return "ok", ""\n\n\ndef sentinel_blocks_action(state_dir: Path):\n    if (state_dir / "show_mode").exists():\n        return "show mode is on"\n    if (state_dir / "sync_in_progress").exists():\n        return "a content sync is running"\n    return None\n\n\ndef recover(serial: str, mode: str, log: sf.Log):\n    """Least invasive action that could work, by default. A wake keyevent is\n    enough if the display merely powered off; the full sleep->wake cycle\n    (what screenRefresh.sh does, and what the operator reports fixes this) is\n    available but is the bigger hammer."""\n    if mode == "cycle":\n        log.line("recovery: sleep -> wake cycle", serial)\n        sf.shell(serial, f"input keyevent {KEYCODE_SLEEP}", timeout=15)\n        time.sleep(1)\n        sf.shell(serial, f"input keyevent {KEYCODE_WAKEUP}", timeout=15)\n    else:\n        log.line("recovery: wake keyevent", serial)\n        sf.shell(serial, f"input keyevent {KEYCODE_WAKEUP}", timeout=15)\n\n\ndef parent_alive(parent_pid):\n    if not parent_pid:\n        return True\n    try:\n        os.kill(int(parent_pid), 0)\n        return True\n    except (OSError, ValueError):\n        return False\n\n\ndef main():\n    ap = argparse.ArgumentParser(description=__doc__,\n                                  formatter_class=argparse.RawDescriptionHelpFormatter)\n    ap.add_argument("--package", required=True)\n    ap.add_argument("--interval", type=int, default=20,\n                     help="Seconds between sampling passes. Kept high by default: this polls every "\n                          "headset over the same AP the fleet streams video through")\n    ap.add_argument("--arm-display-off", action="store_true",\n                     help="Allow recovery for the unambiguous display-off case (Case A). Off by "\n                          "default. Case B (display on, rendering black) is never acted on by this "\n                          "tool regardless of this flag")\n    ap.add_argument("--consecutive", type=int, default=3,\n                     help="How many consecutive samples must show the fault before acting -- guards "\n                          "against a single unlucky read")\n    ap.add_argument("--recovery", choices=["wake", "cycle"], default="wake",\n                     help="wake = wake keyevent only (default, least invasive); "\n                          "cycle = sleep->wake, the heavier fix")\n    ap.add_argument("--cooldown", type=int, default=120)\n    ap.add_argument("--state-dir", default=str(Path.home() / ".cxvr_control_panel"))\n    ap.add_argument("--parent-pid")\n    args = ap.parse_args()\n\n    state_dir = Path(args.state_dir)\n    state_dir.mkdir(parents=True, exist_ok=True)\n    log_dir = state_dir / "logs"\n    log_dir.mkdir(parents=True, exist_ok=True)\n    run_stamp = f"{datetime.now():%Y%m%d_%H%M%S}"\n    log = sf.Log(log_dir / f"black_screen_probe_{run_stamp}.log")\n\n    csv_dir = state_dir / "probe_data"\n    csv_dir.mkdir(parents=True, exist_ok=True)\n    csv_path = csv_dir / f"black_screen_probe_{run_stamp}.csv"\n    csv_file = open(csv_path, "w", newline="", encoding="utf-8")\n    writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)\n    writer.writeheader()\n\n    mode = ("ARMED for display-off recovery" if args.arm_display_off\n            else "OBSERVE-ONLY (no recovery will be sent)")\n    log.line(f"blackScreenProbe starting -- {mode}; interval={args.interval}s "\n              f"consecutive={args.consecutive} recovery={args.recovery}")\n    log.line(f"per-sample data: {csv_path}")\n    log.line("Case B (display ON but rendering black) is recorded, never acted on -- pick a "\n              "threshold from this data across real transitions before automating it.")\n\n    streak = {}\n    last_action = {}\n\n    while True:\n        if not parent_alive(args.parent_pid):\n            log.line("parent process is gone -- exiting")\n            break\n        try:\n            devices = [s for s, st in sf.adb_devices().items() if st == "device"]\n        except Exception as e:\n            log.line(f"could not enumerate devices: {e}")\n            devices = []\n\n        for serial in devices:\n            try:\n                sample = sample_device(serial, args.package)\n            except Exception as e:\n                log.line(f"sampling failed: {e}", serial)\n                continue\n\n            verdict, note = classify(sample)\n            sample["verdict"] = verdict\n            sample["note"] = note\n            writer.writerow({k: sample.get(k) for k in CSV_FIELDS})\n            csv_file.flush()\n\n            if verdict == "display_off_during_app":\n                streak[serial] = streak.get(serial, 0) + 1\n                if streak[serial] == 1:\n                    log.line(f"display appears off while the app is foreground "\n                              f"(sample 1 of {args.consecutive} needed)", serial)\n            else:\n                if streak.get(serial):\n                    log.line(f"condition cleared after {streak[serial]} sample(s)", serial)\n                streak[serial] = 0\n                continue\n\n            if streak[serial] < args.consecutive:\n                continue\n\n            if not args.arm_display_off:\n                log.line(f"[observe-only] would recover now ({args.recovery}) -- "\n                          f"{args.consecutive} consecutive samples with the display off "\n                          f"while the app is foreground", serial)\n                streak[serial] = 0\n                continue\n\n            blocked = sentinel_blocks_action(state_dir)\n            if blocked:\n                log.line(f"would recover, but action is suppressed ({blocked})", serial)\n                streak[serial] = 0\n                continue\n\n            if time.time() - last_action.get(serial, 0) < args.cooldown:\n                streak[serial] = 0\n                continue\n\n            last_action[serial] = time.time()\n            recover(serial, args.recovery, log)\n            streak[serial] = 0\n\n        for _ in range(args.interval):\n            if not parent_alive(args.parent_pid):\n                log.line("parent process is gone -- exiting")\n                csv_file.close()\n                log.close()\n                return 0\n            time.sleep(1)\n\n    csv_file.close()\n    log.close()\n    return 0\n\n\nif __name__ == "__main__":\n    sys.exit(main())\n',
}


def materialize_scripts():
    """Write every embedded script out to a private cache directory and
    make it executable, so it can be invoked exactly like the original
    standalone files always were. Re-writes on every launch so the cache
    can never silently drift from what's embedded in this file -- if you
    want to change a script's behavior, edit the ORIGINAL .sh/.py source
    and regenerate the embedded block, not the materialized copy (which
    gets overwritten on next launch)."""
    SCRIPTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for filename, content in EMBEDDED_SCRIPTS.items():
        if filename == "massConnect.sh":
            content = content.replace("__CXVR_SUBNET_PREFIX__", CXVR_SUBNET_PREFIX)
        path = SCRIPTS_CACHE_DIR / filename
        path.write_text(content)
        if filename.endswith(".sh"):
            path.chmod(0o755)
    return SCRIPTS_CACHE_DIR

def popen_in_own_group(cmd, **kwargs):
    """Launch a subprocess in its own process group/session, so it and any
    children it spawns (e.g. backgrounded `adb` calls inside a bash script)
    can be killed as a unit. Without this, interrupting only the top-level
    process can leave an orphaned hung child holding stdout open forever."""
    if sys.platform == "win32":
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def kill_process_group(proc, force: bool):
    """Signal every process in proc's group, not just proc itself.
    force=False -> graceful interrupt (Ctrl+C equivalent); force=True ->
    unconditional kill of the whole tree."""
    if sys.platform == "win32":
        if force:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                            capture_output=True, check=False)
        else:
            try:
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            except Exception:
                proc.terminate()
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL if force else signal.SIGINT)
    except ProcessLookupError:
        pass  # already gone


def compute_tile_layout(n, region_w=1920, region_h=1080, offset_x=0, offset_y=0, title_bar_height=0):
    """Return a list of (x, y, width, height) window rects, one per item,
    arranged in a roughly-square grid that evenly divides the given region
    (region_w x region_h, anchored at offset_x/offset_y -- e.g. offset_x=960
    for tiling within just the right half of a 1920-wide screen). Pure/no
    side effects so it's testable on its own.

    title_bar_height compensates for scrcpy's --window-height only sizing
    the video content, not the OS title bar drawn on top of it -- without
    this, stacked rows drift/overlap since each row's real on-screen
    footprint is taller than the content height alone. Row-to-row Y
    spacing is still based on the FULL cell height (title bar included);
    only the returned window height is reduced by title_bar_height, so the
    content area plus its title bar together fill exactly one cell."""
    if n <= 0:
        return []
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    cell_w = region_w // cols
    cell_h = region_h // rows
    content_h = max(cell_h - title_bar_height, 1)
    layout = []
    for i in range(n):
        row, col = divmod(i, cols)
        layout.append((offset_x + col * cell_w, offset_y + row * cell_h, cell_w, content_h))
    return layout


SUMMARY_PATTERNS = {
    "connected": re.compile(r"Connected & stable:\s*(\d+)"),
    "confirmed": re.compile(r"Fixed & confirmed this run:\s*(\d+)"),
    "failed": re.compile(r"FAILED to confirm:\s*(\d+)"),
    "total_fixed": re.compile(r"TOTAL stable with fix applied:\s*(\d+)\s*/\s*(\d+)"),
}


def load_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text())
            merged = dict(DEFAULT_CONFIG)
            merged.update(cfg)
            return merged
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


# ---------------------------------------------------------------------------
# Built-in terminal (pinned under the live log)
# ---------------------------------------------------------------------------
# A line-based terminal: each session runs inside a real pseudo-terminal, so a
# local shell or `adb shell` behaves the way it does in a desktop terminal
# (prompt, cd, Ctrl+C), but the panel only renders plain text. Colour and
# cursor-control sequences are stripped, TERM=dumb tells programs not to send
# them, and full-screen programs (vim, top, less) aren't supported. POSIX only.
try:
    import fcntl
    import pty
    import struct
    import termios
    TERMINAL_SUPPORTED = True
except ImportError:   # Windows
    TERMINAL_SUPPORTED = False

TERMINAL_LOCAL_LABEL = "This computer"
TERMINAL_MAX_LINES = 5000

# Complete escape sequences: CSI (colours, cursor moves, bracketed paste),
# OSC (window titles), charset selection, and any other two-byte escape.
_TERM_ESCAPE_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[()][0-9A-Za-z]|[^\[\]()])")
_TERM_CONTROL_RE = re.compile(r"(\r\n|\r|\n|\x08)")


class TerminalStream:
    """Turns raw pty output into simple drawing operations for a Tk Text:
    ("text", s), ("nl",), ("cr",) and ("bs",). Pure (no Tk), so it's testable
    on its own. Holds back an escape sequence or a UTF-8 character that's
    split across two reads, so it never leaks half a sequence as text."""

    def __init__(self):
        import codecs
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._pending = ""

    def feed(self, data: bytes):
        text = self._pending + self._decoder.decode(data)
        self._pending = ""
        esc = text.rfind("\x1b")
        if esc != -1 and not _TERM_ESCAPE_RE.match(text, esc):
            if len(text) - esc < 64:
                self._pending = text[esc:]   # probably completed by the next read
                text = text[:esc]
            else:
                text = text[:esc] + text[esc + 1:]   # malformed -- drop the stray ESC
        text = _TERM_ESCAPE_RE.sub("", text)
        ops = []
        for part in _TERM_CONTROL_RE.split(text):
            if not part:
                continue
            if part in ("\r\n", "\n"):
                ops.append(("nl",))
            elif part == "\r":
                ops.append(("cr",))
            elif part == "\x08":
                ops.append(("bs",))
            else:
                # Tabs stay; every other control character (bell etc.) is dropped.
                clean = "".join(ch for ch in part if ch == "\t" or ch >= " ")
                if clean:
                    ops.append(("text", clean))
        return ops


def set_pty_size(fd, rows, cols):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def spawn_terminal_session(argv, rows=24, cols=80, cwd=None):
    """Starts argv on a new pseudo-terminal. Returns (proc, master_fd).

    The child becomes a session leader with the pty as its controlling
    terminal (util-linux `setsid -c`), which is what makes Ctrl+C interrupt
    whatever is running in the shell rather than nothing at all. Without
    `setsid` it still runs in its own session, just without job control."""
    master, slave = pty.openpty()
    try:
        set_pty_size(master, rows, cols)
        env = dict(os.environ, TERM="dumb", PAGER="cat", GIT_PAGER="cat", SYSTEMD_PAGER="cat",
                   MANPAGER="cat")
        setsid = shutil.which("setsid")
        if setsid:
            cmd, extra = [setsid, "-c"] + list(argv), {}
        else:
            cmd, extra = list(argv), {"start_new_session": True}
        proc = subprocess.Popen(cmd, stdin=slave, stdout=slave, stderr=slave, env=env,
                                cwd=cwd, close_fds=True, **extra)
    except Exception:
        os.close(master)
        os.close(slave)
        raise
    os.close(slave)
    return proc, master


def _terminal_session_members(session_id):
    """Every process (on Linux, via /proc) that belongs to one terminal
    session -- the shell plus anything started from it, including background
    jobs, which sit in process groups of their own."""
    members = []
    try:
        entries = os.listdir("/proc")
    except OSError:
        return members
    for entry in entries:
        if entry.isdigit():
            try:
                if os.getsid(int(entry)) == session_id:
                    members.append(int(entry))
            except OSError:
                pass
    return members


def end_terminal_session(proc):
    """Ends a terminal session the way closing a terminal window would, but
    without leaving background jobs behind: SIGHUP, then SIGKILL, to every
    process in the session, then the shell itself.

    Only ever signals a session confirmed to be the shell's own (its session
    id and process group are the shell's pid, and differ from this panel's),
    so nothing outside it -- this panel included -- can be hit."""
    if proc is None or getattr(proc, "pid", 0) <= 1 or proc.poll() is not None:
        return
    members = []
    try:
        if os.getsid(proc.pid) == proc.pid == os.getpgid(proc.pid) and os.getsid(0) != proc.pid:
            members = [pid for pid in _terminal_session_members(proc.pid) if pid != os.getpid()]
            if not members:   # no /proc (macOS): the shell's own group is the best available
                os.killpg(proc.pid, signal.SIGHUP)
    except OSError:
        members = []
    for sig in (signal.SIGHUP, signal.SIGKILL):
        for pid in members:
            try:
                os.kill(pid, sig)
            except OSError:
                pass
    try:
        proc.kill()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Look & feel -- the "sectioned cards" layout
# ---------------------------------------------------------------------------
# One flat ground colour for the whole window, so ttk widgets placed inside
# cards never need per-container background styles; cards are told apart by
# a 1px border and a tinted header strip instead. The accent is used
# sparingly: one primary action per screen, running-state indicators, and
# Stop buttons. The warning colour marks the two actions that can't be undone
# remotely (Power Off, Delete Video) and anything "armed".
UI_GROUND = "#F2F0EC"
UI_HEAD = "#E6E2DB"
UI_LINE = "#CDC8BF"
UI_TEXT = "#1E1D1B"
UI_MUTED = "#555149"
UI_ACCENT = "#1D5C69"
UI_ACCENT_DARK = "#143F48"
UI_WARN = "#8A3F00"
UI_WARN_BG = "#FBE6D2"
UI_DOT_OFF = "#B3ADA3"
UI_PILL_IDLE_BG = "#E0DCD4"
UI_PILL_IDLE_FG = "#45413B"

# Longer explanations shown by each ? button -- the original on-screen wording,
# moved behind a click so it no longer sits between the controls.
HELP = {
    "terminal": "A terminal built into the panel. Choose where it runs on the right: This computer (your normal shell, starting in your home folder) or a connected headset (the same as running adb -s <headset> shell). Pick one and click Open; opening a different one ends the current session. Refresh re-reads the connected headsets.\n\nType a command on the line at the bottom and press Enter. Up/Down recall earlier commands. Ctrl+C (the key, or the button) interrupts whatever is running; Ctrl+D on an empty line ends the session, as does typing exit. The command line hides what you type while a local program asks for a password.\n\nIt shows plain text only: colours are stripped, and full-screen programs (vim, top, less, nano) won't work. Pagers are switched off, so man and git print straight through. Tab completion isn't available.\n\nCommands run immediately, exactly as typed, on the machine or headset you picked. Show Mode and the sync brake don't apply here -- they only stop the automated watchdogs. Closing the panel ends every terminal session.",
    "sync_app_root": "When checked, only files/Video and files/Media underneath the folder above are scanned and synced -- everything else (Unity's shader cache, runtime metadata, v3.local, the manifests) is never even looked at, let alone pushed. The on-device app root comes from the built-in app package unless Remote target is set explicitly. Leave unchecked if Content folder already contains only the video/image content itself.",
    "sync_remote_target": "Exact on-device folder Headjack reads video from (find it with: adb shell find /sdcard -iname '*.mp4' on a headset that already has working content, then paste the containing folder here). If the checkbox above is checked, this should instead be the app's on-device root (/sdcard/Android/data/<package>) -- leave it blank to have this derived automatically from the built-in app package.",
    "sync_clean_stale": "Headjack's own per-device download record can end up claiming a file exists when it doesn't -- most commonly after cloning one headset's whole Android/data folder to another. This only blanks entries where the file is confirmed missing (backs up the original on-device first) -- never touches an entry whose file actually exists, and doesn't affect playback either way.",
    "sync_catalog": "Content is organized on-device by an opaque ID Headjack's CMS assigned, in a folder per ID -- if a local folder name is a typo or leftover from removed content, it pushes fine but the app will never show or play it, since playback is driven by its own catalog, not by what's physically on disk. This only warns (in the log) -- it never blocks or skips a push.",
    "sync_verify_hash": "Full remote reconciliation (whenever there's no cached state from a previous run, or Verify Mode) compares files by size by default -- fast, and reads only file metadata rather than every byte. This forces a full MD5 content hash instead, computed on the headset's own CPU -- byte-exact, but reading and hashing many GB of video can take minutes and may time out, in which case that headset is safely skipped for the run rather than risking an unnecessary full re-push. Leave unchecked unless you specifically suspect a same-size-but-different-content collision.",
    "sync_prune": "Combined with Dry Run (top of this menu): completely safe -- nothing is deleted, you just get the actual filenames of everything that WOULD be removed (useful when a device reports a large number of \"extra on device\" files and you want to see what they actually are before deciding anything). Combined with a real Sync Content or Verify Mode run: those files are actually deleted from the device. Headjack's own bookkeeping (v3.local, shader cache, manifests, etc.) is never eligible for deletion regardless of this setting.",
    "sync_keep_screen": "Off by default. A sync already keeps WiFi awake regardless of screen state, which is what actually prevents a headset dropping off ADB mid-sync -- this extra setting only forces the screen itself on, which some chargers can't supply enough power to offset, net-draining a headset that appears to be charging. Only turn this on if you specifically want a headset visibly active during a sync and know its charger can handle it.",
    "sync_devices": "Comma-separated serials, as listed by Connect / Reconnect Headsets > Full Scan. Leave blank for all connected headsets.",
    "sync_workers": "Max headsets synced in parallel. Default 6 -- matches the diagnosed 802.11ac MU-MIMO 4-client-per-group plateau; going higher rarely helps and makes each individual transfer slower to retry.",
    "sync_min_free": "Safety margin kept free on each headset's storage at all times. A push that wouldn't fit within this margin is skipped rather than started and left incomplete. Default 300.",
    "sync_skip_power": "Off by default. Normally every sync sets WiFi to never sleep on each device (what actually prevents ADB dropping mid-sync), plus Keep screen on above if checked. Only turn this on if you're managing power settings some other way and want this run to leave them untouched.",
    "sync_skip_register": "Off by default. Content pushed directly by this tool bypasses Headjack's own downloader, which is normally what tells the app (and whatever it reports upstream) that a video or image is actually installed -- so after every successful push, the corresponding files/v3.local entry is filled in if it was previously empty or missing. Never overwrites an entry that's already marked installed. Uses the built-in app package. Only turn this off if you'd rather leave that bookkeeping to the app's own downloader.",
    "sync_connect_file": "Optional file of host:port lines to `adb connect` before scanning devices -- useful for reconnecting headsets that dropped off wireless ADB entirely, not just ones that are connected but stale.",
    "sync_state_dir": "Where trusted per-device state and logs are stored. Leave blank for the default (~/.cxvr_sync).",
    "sync_diagnose": "Checks the laptop's own network link, a single-headset baseline push rate, a concurrency scaling test across connected headsets (up to the max above, capped by however many are actually connected), and each one's WiFi link quality -- then reports whether speed is capped by a shared bottleneck or has room to grow with more workers. Raise the max concurrency here to see if throughput keeps climbing past your normal --workers count, or has already plateaued by then. Uses a generated test file, doesn't touch your actual content. Doesn't need the Content folder field set.",
    "sleepwake_headtracking": "Headtracking Watchdog runs by default, waits for a headset before starting, and rechecks every 60s -- won't re-wake a device that just failed to confirm for a while.\n\nVerbose watchdog output (requires Stop then Start to apply -- also always logged to ~/.cxvr_headtracking_fix/batch_fix_*.log either way)",
    "sleepwake_popup": "Popup/Crash Recovery checks each headset's foreground app against the built-in app package, and sends the HOME button (same as scrcpy's middle-click) if something else -- an overheat warning, an ANR/crash dialog, having dropped to the launcher -- has taken over. This is a best-effort heuristic (checks the focused window via dumpsys), not verified against every possible popup on this hardware -- worth deliberately triggering one on a single headset and watching this watchdog's log before trusting it fleet-wide unattended. Rate-limited per headset so a genuine crash loop doesn't get hammered.",
    "screencap_batch": "Keeps {…} windows open at fixed positions filling the RIGHT HALF of a 1920x1080 screen. Each window times its OWN swap independently, starting from when IT last confirmed a connection -- not a synchronized group swap -- so as soon as one window's timer elapses, just that one closes and the next headset in the queue opens at the same position, while the other windows keep running on their own schedules. Loops back to the start once every connected headset has been shown. Respects the crop checkbox below. Runs independently of Connect/Capture All/Close All -- stopping or starting this doesn't affect windows opened by those.",
    "screencap_about": "Requires scrcpy (https://github.com/Genymobile/scrcpy) installed separately and on PATH. Connect opens one headset; Capture All opens every currently-connected headset at once, tiled evenly across a 1920x1080 layout using scrcpy's own window position/size flags. They stay separate windows -- scrcpy can't merge several devices into one literal window -- just arranged so they don't overlap. The title bar height above is subtracted from each tile's video area so rows still line up correctly with a visible title bar (needed to tell windows apart) -- adjust it if tiles don't quite line up on your system, since it varies by OS/window manager/theme. Close All only closes windows this app opened -- a capture you started by hand outside this app is left alone. Click Refresh after connecting/disconnecting headsets to update the list.\n\nGrouping (above) gives every batch window the same window class, which is what Linux taskbars actually group by -- so they collapse into one taskbar entry you can hover to pick out a single headset, instead of one entry per headset. Windows opened by Connect are deliberately left ungrouped so an individual headset you're working on stays separate. Whether hovering shows live thumbnails depends on your desktop environment; if yours ignores this, nothing breaks -- the windows simply don't group, and you can turn this back off.",
    "debug_adb": "Transparently logs the exact command line and timestamp of every adb call made by any part of this app -- one-shot actions, and any background watchdog started or restarted while this is on -- with zero change to their actual behavior (every call still goes through to the real adb exactly as before, this just also writes a copy of what was sent to a log file). Useful for confirming exactly what's being sent to a device and when, e.g. to rule out something issuing an unexpected reboot.\n\nNote: a watchdog/toggle already running before you start this won't be captured until you Stop and Start it again, since it already inherited the un-instrumented environment when it launched.",
    "overheat": "The overheat prompt dismisses with BACK (what scrcpy's right-click sends). That makes this watchdog different from Popup / Crash Recovery, which sends HOME: HOME is harmless if it fires on a healthy headset, but BACK inside the app could exit playback -- so this one only ever acts on a positive match for the prompt itself, never as a general fallback.\n\nIt ships UNARMED because the prompt's real signature on this hardware hasn't been captured yet. Run it unarmed first, trigger a real overheat, then check the log and Debug Tools > Diagnostic Snapshot to find the actual signature, narrow the match pattern to it, and only then arm it.\n\nArming, the pattern and the interval take effect the next time it starts. Show Mode and a running sync both suspend its actions without stopping it.",
    "blackscreen": "Records each headset's display power state, foreground app, audio and temperature to a CSV every interval, and logs when a fault looks likely.\n\nIt only ever acts on the UNAMBIGUOUS case: the display genuinely powered OFF while the app is still in front. That can't be confused with the black frames between films, because those happen with the display ON. The other case -- display on but rendering black -- is recorded and never acted on, because separating it from a long film transition needs a threshold measured from this tool's own data across a real show, not a guessed one.\n\n\"wake\" just sends a wake keyevent; \"cycle\" does the full sleep -> wake that the quick action performs. Settings take effect the next time it starts. Show Mode and a running sync both suspend its actions without stopping it.",
    "snapshot": "Read-only: sends no input and changes no settings. Dumps display power state, the FULL window list, activities, audio/media session, SurfaceFlinger, thermal/battery, a logcat tail and (optionally) a screenshot into a timestamped folder, with a SUMMARY.txt digesting the lines that matter.\n\nIt exists to answer two questions that can't be answered from the outside: whether the overheat prompt actually takes window focus (if it's a non-focusable overlay, a focus-only check can't see it), and whether a black screen means the display is genuinely POWERED OFF as opposed to on-but-rendering-black.\n\nUse more than one pass when catching something transient like the overheat prompt -- you don't have to hit the button at exactly the right moment."
}


# ---------------------------------------------------------------------------
# Qt port: compatibility layer
# ---------------------------------------------------------------------------
# The logic at the bottom of ControlPanel is the Tkinter panel's own code. It
# still talks to settings variables, message boxes, file pickers and a handful
# of widgets the way it did under Tk (var.get()/set(), messagebox.askyesno(...),
# button.configure(state="disabled"), toggle.configure(text="Stop ..."),
# combo.configure(values=[...])). The classes here give it that same small API
# on top of Qt, so the logic itself never had to be rewritten.

LOG_MAX_LINES = 20000            # on-screen log only; the scripts' own log files are complete
LOG_PUMP_INTERVAL_MS = 100       # also what lets SIGTERM/SIGINT handlers run (see main())
LOG_PUMP_MAX_ITEMS = 2000        # per tick, so a flood of output can't freeze the window

_MAIN_THREAD = threading.main_thread()
# Tests set CXVR_ASSERT_MAIN_THREAD=1: anything that touches a widget from a
# worker thread then fails loudly instead of misbehaving later. (Tk tolerated
# some of that; Qt can crash.) The panel's worker threads only ever post to
# log_queue, which is what keeps them away from widgets.
ASSERT_MAIN_THREAD = os.environ.get("CXVR_ASSERT_MAIN_THREAD") == "1"
THREAD_VIOLATIONS = []


def _assert_main_thread(where):
    if ASSERT_MAIN_THREAD and threading.current_thread() is not _MAIN_THREAD:
        THREAD_VIOLATIONS.append(where)
        raise AssertionError(f"{where} called from worker thread {threading.current_thread().name}")


class Var:
    """A settings value shared by the logic and whichever widgets show it --
    the Qt stand-in for tk.StringVar / tk.BooleanVar. Plain Python, so a
    worker thread may read it (three settings are read from scrcpy threads).
    Widgets bind to it both ways; only the main thread ever sets one that a
    widget is bound to."""
    _default = ""

    def __init__(self, value=None):
        self._value = self._coerce(self._default if value is None else value)
        self._traces = {}
        self._next_token = 0

    @staticmethod
    def _coerce(value):
        return value

    def get(self):
        return self._value

    def set(self, value):
        value = self._coerce(value)
        if value == self._value and type(value) is type(self._value):
            return
        self._value = value
        if self._traces:
            _assert_main_thread("Var.set (bound to a widget)")
            for callback in list(self._traces.values()):
                callback(value)

    def trace_add(self, callback):
        token = self._next_token
        self._next_token += 1
        self._traces[token] = callback
        return token

    def trace_remove(self, token):
        self._traces.pop(token, None)

    def trace_count(self):
        return len(self._traces)


class StringVar(Var):
    _default = ""

    @staticmethod
    def _coerce(value):
        return value if isinstance(value, str) else str(value)


class BooleanVar(Var):
    _default = False

    @staticmethod
    def _coerce(value):
        # Same rules as Tcl's getboolean, which is what tk.BooleanVar.get() uses.
        if isinstance(value, str):
            text = value.strip().lower()
            if text in ("1", "true", "yes", "on"):
                return True
            if text in ("0", "false", "no", "off", ""):
                return False
            raise ValueError(f"expected a boolean, got {value!r}")
        return bool(value)


def _bind(widget, var, on_change):
    """Calls on_change(value) whenever var changes, for as long as the widget
    exists. The link is dropped when the widget is destroyed, so pages that are
    rebuilt every time they're opened never pile up stale bindings."""
    token = var.trace_add(lambda value: on_change(value) if _qt_alive(widget) else None)
    widget.destroyed.connect(lambda *_: var.trace_remove(token))
    widget._cxvr_var = var


def _mnemonic_safe(text):
    """Qt treats a single & in button and checkbox text as a keyboard-shortcut
    marker and hides it ("Purge & Reconnect" would lose its &)."""
    return str(text).replace("&", "&&")


# ------------------------------------------------------------------ dialogs
_dialog_parent_ref = []   # the main window, once it exists


def _dialog_parent():
    parent = _dialog_parent_ref[0] if _dialog_parent_ref else None
    return parent if parent is not None and _qt_alive(parent) else None


class _MessageBoxShim:
    """tkinter.messagebox's names and wording, shown with QMessageBox. Every
    yes/no confirmation defaults to No, so a reflexive Enter never starts a
    sleep, a mute, a reboot or a delete (the Tkinter panel defaulted to Yes)."""

    @staticmethod
    def _show(icon, title, message, buttons, default, escape):
        _assert_main_thread("messagebox")
        box = QMessageBox(icon, str(title or ""), str(message or ""), buttons, _dialog_parent())
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setDefaultButton(default)
        box.setEscapeButton(escape)
        return box.exec()

    def showinfo(self, title=None, message=None, **options):
        self._show(QMessageBox.Icon.Information, title, message, QMessageBox.StandardButton.Ok,
                   QMessageBox.StandardButton.Ok, QMessageBox.StandardButton.Ok)
        return "ok"

    def showwarning(self, title=None, message=None, **options):
        self._show(QMessageBox.Icon.Warning, title, message, QMessageBox.StandardButton.Ok,
                   QMessageBox.StandardButton.Ok, QMessageBox.StandardButton.Ok)
        return "ok"

    def showerror(self, title=None, message=None, **options):
        self._show(QMessageBox.Icon.Critical, title, message, QMessageBox.StandardButton.Ok,
                   QMessageBox.StandardButton.Ok, QMessageBox.StandardButton.Ok)
        return "ok"

    def askyesno(self, title=None, message=None, **options):
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        return self._show(QMessageBox.Icon.Question, title, message, yes | no, no, no) == yes


class _FileDialogShim:
    """tkinter.filedialog's names; returns "" when cancelled, like Tk."""

    @staticmethod
    def askdirectory(title=None, **options):
        _assert_main_thread("filedialog")
        return QFileDialog.getExistingDirectory(_dialog_parent(), str(title or "")) or ""

    @staticmethod
    def askopenfilename(title=None, **options):
        _assert_main_thread("filedialog")
        path, _filter = QFileDialog.getOpenFileName(_dialog_parent(), str(title or ""))
        return path or ""


messagebox = _MessageBoxShim()
filedialog = _FileDialogShim()


# ------------------------------------------------------------------ widgets
class Button(QPushButton):
    """A push button that also answers the few Tk calls the logic makes:
    configure(state=/text=), cget("text"/"state") and invoke()."""

    def __init__(self, text="", command=None, kind=None, parent=None, tooltip=None):
        super().__init__(parent)
        self._label = ""
        self._command = command
        self.set_label(text)
        if kind:
            self.setObjectName(kind)
        if tooltip:
            self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._on_clicked)

    def _on_clicked(self, *_):
        if self._command is not None:
            self._command()

    def set_label(self, text):
        self._label = str(text)
        self.setText(_mnemonic_safe(text))

    def label(self):
        return self._label

    def configure(self, cnf=None, **kw):
        _assert_main_thread("Button.configure")
        if isinstance(cnf, dict):
            kw = {**cnf, **kw}
        if "state" in kw:
            self.setEnabled(str(kw["state"]) != "disabled")
        if "text" in kw:
            self.set_label(kw["text"])
        if "command" in kw:
            self._command = kw["command"]

    config = configure

    def cget(self, key):
        if key == "text":
            return self._label
        if key == "state":
            return "normal" if self.isEnabled() else "disabled"
        raise KeyError(key)

    def invoke(self):
        if self.isEnabled():
            self.click()


class Entry(QLineEdit):
    """A text field bound to a StringVar (ttk.Entry with textvariable=)."""

    def __init__(self, var, chars=None, parent=None):
        super().__init__(parent)
        self._var = var
        self._syncing = False
        self.setText(var.get())
        self.textChanged.connect(self._to_var)
        _bind(self, var, self._from_var)
        if chars:
            self.setFixedWidth(self.fontMetrics().horizontalAdvance("0" * chars) + 22)

    def _to_var(self, text):
        if not self._syncing:
            self._var.set(text)

    def _from_var(self, value):
        if self.text() != value:
            self._syncing = True
            try:
                self.setText(value)
            finally:
                self._syncing = False


class Check(QCheckBox):
    """A checkbox bound to a BooleanVar. Like a ttk.Checkbutton, clicking sets
    the variable first and then runs the command."""

    def __init__(self, text, var, command=None, parent=None):
        super().__init__(_mnemonic_safe(text), parent)
        self._label = str(text)
        self._var = var
        self._command = command
        self.setChecked(bool(var.get()))
        self.clicked.connect(self._on_clicked)
        _bind(self, var, lambda value: self.setChecked(bool(value)) if self.isChecked() != bool(value) else None)

    def _on_clicked(self, checked):
        self._var.set(bool(checked))
        if self._command is not None:
            self._command()

    def label(self):
        return self._label

    def invoke(self):
        self.click()


class Combo(QComboBox):
    """A read-only dropdown bound to a StringVar (a readonly ttk.Combobox).
    configure(values=[...]) replaces the list, as it did under Tk. A value the
    logic sets that isn't in the list (yet) is still shown, greyed, rather than
    silently replaced. The mouse wheel never changes it: scrolling the page
    over a headset picker must not quietly retarget an action."""

    def __init__(self, var, values=(), chars=24, parent=None):
        super().__init__(parent)
        self._var = var
        self._values = [str(v) for v in values]
        self.addItems(self._values)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(chars)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.activated.connect(self._on_activated)
        _bind(self, var, self._show_value)
        self._show_value(var.get())

    def _on_activated(self, index):
        if 0 <= index < len(self._values):
            self._var.set(self._values[index])

    def _show_value(self, value):
        index = self._values.index(value) if value in self._values else -1
        self.setPlaceholderText("" if index >= 0 else str(value))
        self.setCurrentIndex(index)

    def configure(self, cnf=None, **kw):
        _assert_main_thread("Combo.configure")
        if isinstance(cnf, dict):
            kw = {**cnf, **kw}
        if "values" in kw:
            self._values = [str(v) for v in kw["values"]]
            self.clear()
            self.addItems(self._values)
            self._show_value(self._var.get())
        if "state" in kw:
            self.setEnabled(str(kw["state"]) != "disabled")

    config = configure

    def cget(self, key):
        if key == "values":
            return tuple(self._values)
        raise KeyError(key)

    def choose(self, value):
        """What picking an entry with the mouse does (used by tests)."""
        self._on_activated(self._values.index(value))

    def wheelEvent(self, event):
        event.ignore()

    def paintEvent(self, event):
        super().paintEvent(event)
        # The style sheet hides the native drop-down arrow (it drew a dark edge);
        # draw a plain chevron instead so it still reads as a dropdown.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = painter.pen()
        pen.setColor(QColor(UI_MUTED if self.isEnabled() else "#B8B2A8"))
        pen.setWidthF(1.6)
        painter.setPen(pen)
        cx, cy = self.width() - 13, self.height() / 2
        painter.drawPolyline([QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2)])


class SpinEntry(QWidget):
    """A number field with − and + buttons, bound to a StringVar -- the
    ttk.Spinbox equivalent. Like the Tk one it accepts any text, because the
    logic validates the text itself and reports a bad value in its own words.
    Up/Down in the field step it too; the mouse wheel never does."""

    def __init__(self, var, lo, hi, chars=4, parent=None):
        super().__init__(parent)
        self._lo, self._hi = lo, hi
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        self.down_button = QToolButton()
        self.down_button.setObjectName("stepBtn")
        self.down_button.setText("\u2212")
        self.down_button.setAutoRepeat(True)
        self.down_button.clicked.connect(lambda: self.step(-1))
        self.entry = Entry(var, chars=chars)
        self.entry.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.entry.keyPressEvent = self._entry_key
        self.up_button = QToolButton()
        self.up_button.setObjectName("stepBtn")
        self.up_button.setText("+")
        self.up_button.setAutoRepeat(True)
        self.up_button.clicked.connect(lambda: self.step(1))
        for widget in (self.down_button, self.entry, self.up_button):
            row.addWidget(widget)
        self._cxvr_var = var

    def step(self, steps):
        try:
            value = int(self.entry.text().strip())
        except ValueError:
            value = self._lo if steps > 0 else self._hi
        else:
            value += steps
        self.entry.setText(str(min(self._hi, max(self._lo, value))))

    def _entry_key(self, event):
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.step(1 if event.key() == Qt.Key.Key_Up else -1)
            return
        QLineEdit.keyPressEvent(self.entry, event)


class Switch(QAbstractButton):
    """The on/off switch drawing shared by ToggleSwitch and VarSwitch.
    `warn=True` turns amber when on (Show Mode); everything else uses the accent."""

    def __init__(self, warn=False, parent=None):
        super().__init__(parent)
        self._warn = warn
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(40, 22)

    def _is_on(self):
        return self.isChecked()

    def sizeHint(self):
        return QSize(40, 22)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self._is_on()
        track = QColor(UI_WARN if (on and self._warn) else UI_ACCENT if on else "#C9C3B8")
        if not self.isEnabled():
            track.setAlpha(110)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        knob = rect.height() - 6
        x = rect.right() - knob - 3 if on else rect.left() + 3
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(x, rect.top() + 3, knob, knob))
        if self.hasFocus():
            painter.setPen(QColor(UI_ACCENT_DARK))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                                    rect.height() / 2 + 1, rect.height() / 2 + 1)


class ToggleSwitch(Switch):
    """Start/Stop for anything long-running (watchdogs, batch preview, the ADB
    debug log) -- the Qt stand-in for the Tk panel's ToggleButton.

    It never flips itself when clicked: the click only runs the action, and
    the action says what happened by relabelling it the way the Tk code always
    has -- configure(text="Stop ...") means running, "Start ..." means stopped.
    So a start that's refused (a bad interval, an arm confirmation answered No)
    leaves it off. cget("text") answers "Start" or "Stop", like ToggleButton."""

    def __init__(self, running=False, on_change=None, command=None, parent=None):
        super().__init__(parent=parent)
        self._running = bool(running)
        self._on_change = on_change
        self._command = command
        self.clicked.connect(self._on_clicked)
        self._refresh_tip()

    def _is_on(self):
        return self._running

    def _on_clicked(self, *_):
        if self._command is not None:
            self._command()

    def _refresh_tip(self):
        self.setToolTip("Running — click to stop" if self._running else "Stopped — click to start")
        self.setAccessibleName("Stop" if self._running else "Start")

    def configure(self, cnf=None, **kw):
        _assert_main_thread("ToggleSwitch.configure")
        if isinstance(cnf, dict):
            kw = {**cnf, **kw}
        if "text" in kw:
            self._running = str(kw["text"]).strip().lower().startswith("stop")
            self._refresh_tip()
            self.update()
            if self._on_change is not None:
                try:
                    self._on_change(self._running)
                except RuntimeError:
                    pass   # its row was already torn down by a page switch
        if "command" in kw:
            self._command = kw["command"]
        if "state" in kw:
            self.setEnabled(str(kw["state"]) != "disabled")

    config = configure

    def cget(self, key):
        if key == "text":
            return "Stop" if self._running else "Start"
        if key == "state":
            return "normal" if self.isEnabled() else "disabled"
        raise KeyError(key)

    def invoke(self):
        if self.isEnabled():
            self.click()


class VarSwitch(Switch):
    """A switch bound to a BooleanVar (the Show Mode switch). Like a
    ttk.Checkbutton: clicking sets the variable, then runs the command."""

    def __init__(self, var, command=None, warn=False, parent=None):
        super().__init__(warn=warn, parent=parent)
        self._var = var
        self._command = command
        self.setCheckable(True)
        self.setChecked(bool(var.get()))
        self.clicked.connect(self._on_clicked)
        _bind(self, var, lambda value: self.setChecked(bool(value)) if self.isChecked() != bool(value) else None)

    def _on_clicked(self, checked):
        self._var.set(bool(checked))
        if self._command is not None:
            self._command()

    def invoke(self):
        self.click()


# ---------------------------------------------------------------------------
# Qt port: design system
# ---------------------------------------------------------------------------
# The same palette as the Tkinter panel (UI_* above) plus a few Qt-only tints,
# on top of Qt's Fusion style so it looks the same on any desktop. Rules kept
# from the Tk layout: one primary button per page, the danger style only for
# what can't be undone remotely, actions first and settings after, and long
# explanations behind a "?" button.
UI_SURFACE = "#FBFAF7"
UI_ACCENT_TINT = "#DCE8EA"
UI_SIDEBAR = "#EBE7E0"
UI_CONSOLE_BG = "#101412"
UI_CONSOLE_FG = "#D8E0DA"
UI_LOG_FAIL = "#ff6b6b"
UI_LOG_OK = "#6bcf6b"

UI_FONTS = ["Ubuntu Sans", "Ubuntu", "Noto Sans", "Cantarell", "DejaVu Sans"]
MONO_FONTS = ["Ubuntu Sans Mono", "Ubuntu Mono", "DejaVu Sans Mono", "Monospace"]

QSS = f"""
QMainWindow, QWidget#page {{ background: {UI_GROUND}; }}
QLabel {{ color: {UI_TEXT}; background: transparent; }}
QToolTip {{ color: {UI_TEXT}; background: #FFFFFF; border: 1px solid {UI_LINE}; padding: 4px; }}

QFrame#strip {{ background: {UI_HEAD}; border-bottom: 1px solid {UI_LINE}; }}
QFrame#strip[showmode="true"] {{ background: {UI_WARN_BG}; border-bottom: 1px solid #E3B58C; }}
QLabel#statValue {{ font-size: 13pt; font-weight: 700; }}
QLabel#statValue[warn="true"] {{ color: {UI_WARN}; }}
QLabel#statCaption {{ color: {UI_MUTED}; font-size: 8pt; }}
QLabel#wordmark {{ color: {UI_ACCENT}; font-size: 12pt; font-weight: 800; }}
QLabel#showModeLabel {{ font-weight: 700; }}
QLabel#showModeLabel[on="true"] {{ color: {UI_WARN}; }}
QLabel#showBar {{ background: {UI_WARN}; color: #FFFFFF; font-weight: 700; font-size: 9pt; padding: 5px 16px; }}

QFrame#sidebar {{ background: {UI_SIDEBAR}; border-right: 1px solid {UI_LINE}; }}
QScrollArea#sideScroll {{ background: {UI_SIDEBAR}; border: none; }}
QPushButton#nav {{ text-align: left; padding: 6px 10px 6px 14px; border: none;
    border-left: 3px solid transparent; border-radius: 0; background: transparent; color: {UI_TEXT}; }}
QPushButton#nav:hover {{ background: #E1DCD3; }}
QPushButton#nav:checked {{ background: {UI_ACCENT_TINT}; border-left: 3px solid {UI_ACCENT};
    color: {UI_ACCENT_DARK}; font-weight: 700; }}
QLabel#navBadge {{ background: {UI_WARN_BG}; color: {UI_WARN}; border-radius: 8px; padding: 0 6px;
    font-size: 8pt; font-weight: 700; }}
QLabel#navLater {{ color: #8C867C; font-size: 8pt; }}
QLabel#sideNote {{ color: {UI_MUTED}; font-size: 8pt; }}
QPushButton#paneToggle {{ text-align: left; padding: 3px 8px; border: 1px solid transparent; border-radius: 5px;
    color: {UI_MUTED}; background: transparent; font-size: 9pt; }}
QPushButton#paneToggle:hover {{ border-color: #C4BEB3; }}
QPushButton#paneToggle:checked {{ color: {UI_ACCENT_DARK}; background: {UI_ACCENT_TINT}; }}
QToolButton#stepBtn {{ border: 1px solid #C4BEB3; border-radius: 6px; background: #FFFFFF; min-width: 24px;
    min-height: 26px; font-weight: 700; color: {UI_TEXT}; }}
QToolButton#stepBtn:hover {{ border-color: {UI_ACCENT}; }}

QLabel#pageTitle {{ font-size: 15pt; font-weight: 700; }}
QLabel#caption {{ color: {UI_MUTED}; font-size: 9pt; }}
QLabel#caption[variant="italic"] {{ font-style: italic; }}
QLabel#caption[variant="notice"] {{ color: {UI_WARN}; font-style: italic; }}
QLabel#field {{ font-weight: 700; }}
QLabel#name {{ font-weight: 700; }}

QFrame#card {{ background: {UI_SURFACE}; border: 1px solid {UI_LINE}; border-radius: 8px; }}
QFrame#cardHead {{ background: transparent; border: none; border-bottom: 1px solid #E6E2DA; }}
QFrame#rule {{ background: #E6E2DA; border: none; max-height: 1px; min-height: 1px; }}
QFrame#sectionHead {{ background: transparent; border: none; }}
QFrame#sectionHead:hover {{ background: #F1EEE8; border-radius: 8px; }}
QFrame#banner {{ background: {UI_WARN_BG}; border: 1px solid {UI_WARN}; border-radius: 6px; }}
QFrame#banner QLabel {{ color: {UI_WARN}; }}
QFrame#placeholder {{ background: {UI_SURFACE}; border: 1px dashed #BDB6AA; border-radius: 8px; }}

QPushButton {{ background: #FFFFFF; border: 1px solid #C4BEB3; border-radius: 6px; padding: 6px 14px;
    color: {UI_TEXT}; }}
QPushButton:hover {{ border-color: {UI_ACCENT}; }}
QPushButton:pressed {{ background: #EFEDE8; }}
QPushButton:focus {{ border-color: {UI_ACCENT}; }}
QPushButton:disabled {{ color: #A8A298; border-color: #DDD8CF; background: #F7F5F1; }}
QPushButton#big {{ padding: 9px 14px; }}
QPushButton#primary {{ background: {UI_ACCENT}; color: #FFFFFF; border: 1px solid {UI_ACCENT_DARK};
    font-weight: 700; padding: 9px 14px; }}
QPushButton#primary:hover {{ background: {UI_ACCENT_DARK}; }}
QPushButton#primary:disabled {{ background: #9DB5BA; color: #EEF3F4; border-color: #9DB5BA; }}
QPushButton#danger {{ color: {UI_WARN}; border: 1px solid {UI_WARN}; font-weight: 700; padding: 9px 14px; }}
QPushButton#danger:hover {{ background: {UI_WARN_BG}; }}
QPushButton#danger:disabled {{ color: #C9A88C; border-color: #E3CDB8; background: #F7F5F1; }}
QPushButton#small {{ padding: 3px 10px; font-size: 9pt; }}
QPushButton#stripBtn {{ padding: 4px 10px; font-size: 9pt; background: #F7F5F1; }}
QPushButton#link {{ border: none; background: transparent; color: {UI_ACCENT}; padding: 2px 0; font-weight: 700;
    text-align: left; }}
QPushButton#link:hover {{ text-decoration: underline; }}
QPushButton#help {{ padding: 0; min-width: 20px; max-width: 20px; min-height: 20px; max-height: 20px;
    border-radius: 10px; font-weight: 700; color: {UI_MUTED}; font-size: 9pt; }}

QLabel#pill {{ border-radius: 8px; padding: 1px 8px; font-size: 8pt; font-weight: 700; }}
QLabel#pill[kind="run"] {{ background: {UI_ACCENT}; color: #FFFFFF; }}
QLabel#pill[kind="idle"] {{ background: {UI_PILL_IDLE_BG}; color: {UI_PILL_IDLE_FG}; }}
QLabel#pill[kind="armed"] {{ background: {UI_WARN_BG}; color: {UI_WARN}; }}
QLabel#pill[kind="chip"] {{ background: #F7F5F1; color: {UI_ACCENT_DARK}; border: 1px solid #BFD3D7; }}
QLabel#dot {{ border-radius: 4px; background: {UI_DOT_OFF}; }}
QLabel#dot[on="true"] {{ background: {UI_ACCENT}; }}

QLineEdit, QComboBox {{ background: #FFFFFF; border: 1px solid #C4BEB3; border-radius: 6px;
    padding: 4px 8px; min-height: 20px; color: {UI_TEXT}; }}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {UI_ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox:disabled, QLineEdit:disabled {{ color: #A8A298; background: #F4F2EE; }}
QCheckBox {{ spacing: 7px; }}

QScrollArea#pageScroll {{ border: none; background: {UI_GROUND}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #CFC9BF; border-radius: 3px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #CFC9BF; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMainWindow::separator {{ background: {UI_LINE}; width: 4px; height: 4px; }}
QMainWindow::separator:hover {{ background: #B7B0A5; }}
QMainWindow > QTabBar::tab {{ background: {UI_HEAD}; color: {UI_MUTED}; padding: 5px 16px; border: none;
    font-weight: 700; font-size: 9pt; }}
QMainWindow > QTabBar::tab:selected {{ background: {UI_CONSOLE_BG}; color: #E8EEE9; }}
QFrame#dockTitle {{ background: {UI_HEAD}; border-bottom: 1px solid {UI_LINE}; }}
QToolButton#dockBtn {{ border: 1px solid transparent; border-radius: 4px; padding: 0 5px; color: {UI_MUTED};
    background: transparent; }}
QToolButton#dockBtn:hover {{ border-color: #C4BEB3; background: #F7F5F1; }}
QPlainTextEdit#console {{ background: {UI_CONSOLE_BG}; color: {UI_CONSOLE_FG}; border: none; padding: 4px 6px; }}
QFrame#consoleNote {{ background: {UI_CONSOLE_BG}; }}
QFrame#consoleNote QLabel {{ color: #AFC0B6; }}
"""


def app_font():
    font = QFont()
    font.setFamilies(UI_FONTS)
    font.setPointSizeF(10)
    return font


def mono_font():
    font = QFont()
    font.setFamilies(MONO_FONTS)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSizeF(10)
    return font


def restyle(widget):
    """Re-applies the style sheet after a dynamic property changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def small_caps(text, size=8.0, color=UI_MUTED):
    label = QLabel(str(text).upper())
    font = label.font()
    font.setPointSizeF(size)
    font.setBold(True)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.9)
    label.setFont(font)
    label.setStyleSheet(f"color: {color};")
    return label


def rule():
    line = QFrame()
    line.setObjectName("rule")
    return line


class Caption(QLabel):
    """Muted explanatory text that wraps to whatever width it's given. Unlike
    Tk, Qt re-wraps word-wrapped labels natively, so none of the old re-wrap
    workarounds (and none of the freezes they caused) are needed."""

    def __init__(self, text="", var=None, variant=None, parent=None):
        super().__init__(parent)
        self.setObjectName("caption")
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        if variant:
            self.setProperty("variant", variant)
        if var is not None:
            self.setText(var.get())
            _bind(self, var, self.setText)
        else:
            self.setText(str(text))


def field_label(text):
    label = QLabel(str(text))
    label.setObjectName("field")
    return label


def info_button(title, text):
    """The small ? that shows a longer explanation on demand (the HELP texts)."""
    return Button("?", lambda: messagebox.showinfo(title, text, parent=_dialog_parent()), kind="help",
                  tooltip="More about this")


class Card(QFrame):
    """A titled section: tinted title strip, then a padded body (card.body is a
    QVBoxLayout). `right` widgets go on the right of the title strip; `help`
    is a (title, text) pair shown by a ? button there."""

    def __init__(self, title, right=None, help=None, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.title = str(title)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QFrame()
        head.setObjectName("cardHead")
        self.head_layout = QHBoxLayout(head)
        self.head_layout.setContentsMargins(14, 7, 10, 7)
        self.head_layout.setSpacing(6)
        self.head_layout.addWidget(small_caps(title))
        self.head_layout.addStretch(1)
        for widget in right or []:
            self.head_layout.addWidget(widget)
        if help:
            self.head_layout.addWidget(info_button(*help))
        outer.addWidget(head)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(14, 11, 14, 13)
        self.body.setSpacing(9)
        outer.addLayout(self.body)


class Collapsible(QFrame):
    """A section that starts collapsed to one line (title and a summary).
    Open/closed is remembered for the session in `state` (a dict), so coming
    back to a page keeps it."""

    def __init__(self, key, title, summary, state, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self._key, self._state = key, state
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = QFrame()
        self.header.setObjectName("sectionHead")
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.header.mousePressEvent = lambda event: self.invoke()
        self.header.keyPressEvent = self._header_key
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(14, 8, 12, 8)
        hl.setSpacing(10)
        self._arrow = QLabel()
        self._arrow.setFixedWidth(12)
        hl.addWidget(self._arrow, 0, Qt.AlignmentFlag.AlignTop)
        hl.addWidget(small_caps(title), 0, Qt.AlignmentFlag.AlignTop)
        self._summary = Caption(summary)
        hl.addWidget(self._summary, 1)
        outer.addWidget(self.header)
        self.body_widget = QWidget()
        self.body = QVBoxLayout(self.body_widget)
        self.body.setContentsMargins(14, 4, 14, 13)
        self.body.setSpacing(9)
        outer.addWidget(self.body_widget)
        self._render()

    def is_open(self):
        return bool(self._state.get(self._key, False))

    def _render(self):
        self._arrow.setText("▾" if self.is_open() else "▸")
        self.body_widget.setVisible(self.is_open())

    def invoke(self):
        self._state[self._key] = not self.is_open()
        self._render()

    def _header_key(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.invoke()
        else:
            QFrame.keyPressEvent(self.header, event)


def pill(text, kind):
    label = QLabel(str(text))
    label.setObjectName("pill")
    label.setProperty("kind", kind)
    label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return label


class ModePill(QLabel):
    """Observe only / Armed, following a BooleanVar."""

    def __init__(self, var, armed_text="Armed", idle_text="Observe only", parent=None):
        super().__init__(parent)
        self.setObjectName("pill")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._var, self._armed_text, self._idle_text = var, armed_text, idle_text
        _bind(self, var, lambda value: self.refresh())
        self.refresh()

    def refresh(self):
        armed = bool(self._var.get())
        self.setText(self._armed_text if armed else self._idle_text)
        self.setProperty("kind", "armed" if armed else "idle")
        restyle(self)


class ToggleRow(QWidget):
    """One long-running task: status dot, name (+ a Running pill and an
    optional ?), a caption, optional inline settings, and its ToggleSwitch on
    the right. `settings_layout` is where a page puts inline settings."""

    def __init__(self, title, caption=None, caption_var=None, info=None, running=False, parent=None):
        super().__init__(parent)
        self.title = str(title)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self._dot = QLabel()
        self._dot.setObjectName("dot")
        self._dot.setFixedSize(9, 9)
        dot_box = QVBoxLayout()
        dot_box.setContentsMargins(0, 6, 0, 0)
        dot_box.addWidget(self._dot)
        dot_box.addStretch(1)
        row.addLayout(dot_box)
        text = QVBoxLayout()
        text.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(8)
        name = QLabel(self.title)
        name.setObjectName("name")
        top.addWidget(name)
        self._pill = pill("Running", "run")
        top.addWidget(self._pill)
        if info:
            top.addWidget(info_button(title, info))
        top.addStretch(1)
        text.addLayout(top)
        if caption or caption_var is not None:
            text.addWidget(Caption(caption or "", var=caption_var))
        row.addLayout(text, 1)
        self.settings_layout = QHBoxLayout()
        self.settings_layout.setSpacing(6)
        row.addLayout(self.settings_layout)
        self._switch_box = QVBoxLayout()
        self._switch_box.setContentsMargins(0, 2, 0, 0)
        row.addLayout(self._switch_box)
        self.set_running(running)

    def set_switch(self, switch):
        self.switch = switch
        self._switch_box.addWidget(switch)
        self._switch_box.addStretch(1)

    def set_running(self, running):
        self._pill.setVisible(bool(running))
        self._dot.setProperty("on", bool(running))
        restyle(self._dot)


class TestingBanner(QFrame):
    """The amber strip on a page whose feature hasn't been marked tested yet."""

    def __init__(self, what, destination, on_mark, parent=None):
        super().__init__(parent)
        self.setObjectName("banner")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 8, 8)
        row.setSpacing(10)
        text = QLabel(f"{what} hasn't been marked tested yet, so it only lives under Testing. "
                      f"Marking it tested moves it to {destination}.")
        text.setWordWrap(True)
        text.setTextFormat(Qt.TextFormat.PlainText)
        row.addWidget(text, 1)
        row.addWidget(Button("Mark tested", on_mark, kind="small"), 0, Qt.AlignmentFlag.AlignVCenter)


class ChipRow(QWidget):
    """The running background tasks as chips, in one line. If they don't all
    fit, the last visible chip becomes "+N more" (its tooltip lists them all),
    so a long list can never force the window wider."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(5)
        self._chips = []
        self._more = pill("", "chip")
        self._none = QLabel("none running")
        self._none.setObjectName("statCaption")
        self._row.addWidget(self._none)
        self._row.addWidget(self._more)
        self._row.addStretch(1)
        self._names = []
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def set_names(self, names):
        for chip in self._chips:
            self._row.removeWidget(chip)
            chip.hide()
            chip.deleteLater()
        self._names = list(names)
        self._chips = [pill(name, "chip") for name in self._names]
        for i, chip in enumerate(self._chips):
            self._row.insertWidget(1 + i, chip)
            chip.ensurePolished()   # measure with the style sheet applied, not the bare label
        self.setToolTip("\n".join(self._names))
        self._fit()
        QTimer.singleShot(0, self._fit)

    def names(self):
        return list(self._names)

    def minimumSizeHint(self):
        return QSize(60, max(self._more.sizeHint().height(), self._none.sizeHint().height()))

    def sizeHint(self):
        width = sum(c.sizeHint().width() + 5 for c in self._chips) or self._none.sizeHint().width()
        return QSize(width, self.minimumSizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self):
        if not _qt_alive(self):
            return
        self._more.ensurePolished()
        self._none.setVisible(not self._chips)
        available = self.width()
        used, shown = 0, 0
        for i, chip in enumerate(self._chips):
            need = chip.sizeHint().width() + 5
            rest = len(self._chips) - i - 1
            reserve = 0
            if rest:
                self._more.setText(f"+{rest} more")
                reserve = self._more.sizeHint().width() + 5
            if used + need + reserve <= available or (i == 0 and not rest and need <= available):
                chip.show()
                used += need
                shown += 1
            else:
                break
        for chip in self._chips[shown:]:
            chip.hide()
        hidden = len(self._chips) - shown
        self._more.setText(f"+{hidden} more")
        self._more.setVisible(hidden > 0)


class StatCell(QWidget):
    """One status number with its caption: value above caption (wide strip) or
    side by side (compact strip). configure(foreground=...) is what the Tk
    logic calls to flag a non-zero 'failed' count."""

    def __init__(self, var, caption, parent=None):
        super().__init__(parent)
        self.value = QLabel()
        self.value.setObjectName("statValue")
        self.value.setText(var.get())
        _bind(self.value, var, self.value.setText)
        self.caption = QLabel(caption)
        self.caption.setObjectName("statCaption")
        for label in (self.value, self.caption):
            label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self._layout = QBoxLayout(QBoxLayout.Direction.TopToBottom, self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._layout.addWidget(self.value, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._layout.addWidget(self.caption, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.set_compact(False)

    def set_compact(self, compact):
        self._layout.setDirection(QBoxLayout.Direction.LeftToRight if compact
                                  else QBoxLayout.Direction.TopToBottom)
        self._layout.setSpacing(6 if compact else 0)

    def configure(self, cnf=None, **kw):
        _assert_main_thread("StatCell.configure")
        if isinstance(cnf, dict):
            kw = {**cnf, **kw}
        if "foreground" in kw:
            self.value.setProperty("warn", bool(kw["foreground"]))
            restyle(self.value)

    config = configure


class DockTitle(QFrame):
    """A compact title bar for the Live log / Terminal panes: name, any extra
    buttons (Clear), then float and close. Dragging it or double-clicking it
    works as on any dock, because it leaves those mouse events to the dock."""

    def __init__(self, dock, title, extras=(), parent=None):
        super().__init__(parent)
        self.setObjectName("dockTitle")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 2, 6, 2)
        row.setSpacing(4)
        row.addWidget(small_caps(title, 7.5))
        self.status = QLabel("")
        self.status.setObjectName("statCaption")
        row.addWidget(self.status)
        row.addStretch(1)
        for widget in extras:
            row.addWidget(widget)
        float_btn = QToolButton()
        float_btn.setObjectName("dockBtn")
        float_btn.setText("⧉")
        float_btn.setToolTip("Float this pane (drag it to the other monitor); double-click its title to dock it again")
        float_btn.clicked.connect(lambda: dock.setFloating(not dock.isFloating()))
        close_btn = QToolButton()
        close_btn.setObjectName("dockBtn")
        close_btn.setText("✕")
        close_btn.setToolTip("Hide this pane (bring it back from the bottom of the sidebar)")
        close_btn.clicked.connect(dock.close)
        row.addWidget(float_btn)
        row.addWidget(close_btn)


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------
# Sidebar: (section, ((page key, label), ...)). Delete Video only shows once
# it's marked tested; Testing carries a badge with the number still untested.
NAV_SECTIONS = (
    ("Fleet", (("connect", "Connect"), ("sleepwake", "Sleep / Wake"), ("volume", "Volume"),
               ("power", "Power"), ("heartbeat", "Heartbeat"))),
    ("Content", (("sync", "Content Sync"), ("delete_video", "Delete Video"))),
    ("View & debug", (("screencap", "Screen Capture"), ("debug", "Debug Tools"))),
    ("Not yet tested", (("testing", "Testing"),)),
)
NAV_OPENERS = {
    "connect": "show_menu_connect", "sleepwake": "show_menu_sleepwake", "volume": "show_menu_volume",
    "power": "show_menu_power", "heartbeat": "show_menu_heartbeat", "sync": "show_menu_sync",
    "delete_video": "show_menu_delete_video", "screencap": "show_menu_screencap", "debug": "show_menu_debug",
    "testing": "show_menu_testing",
}
# Pages still on their way over from the Tkinter panel -> the port phase that brings them.
PAGES_NOT_YET_PORTED = {"sleepwake": 2, "sync": 2, "delete_video": 2, "debug": 2, "screencap": 3}

# Friendlier names for the background-task chips (the Tk panel showed the raw names).
TASK_LABELS = {
    "htWatchdog": "Headtracking", "stayAwake": "Stay-Awake", "keepalive": "Keepalive",
    "popupWatchdog": "Popup recovery", "overheatWatchdog": "Overheat", "blackScreenProbe": "Black-screen probe",
    "heartbeat": "Heartbeat",
}

SIDEBAR_WIDTH = 172
STRIP_WIDE_MIN = 1200        # narrower than this, the top strip uses its compact two-row layout
WINDOW_STATE_VERSION = 1     # bump if the dock layout changes shape, so an old saved layout is ignored

SHOW_MODE_HELP = ("While on, the overheat and black-screen watchdogs keep watching and logging but send "
                  "nothing to any headset. Monitoring continues; only the corrective actions stop. Survives "
                  "restarting the panel.\n\nThe other watchdogs (Stay-Awake, Keepalive, Headtracking, Popup "
                  "recovery) don't read Show Mode and keep running as they are.")


def _page(builder):
    """Marks a page builder. The page is put on screen only once the builder
    has filled it, so everything on it appears at once."""
    @functools.wraps(builder)
    def build(self, *args, **kwargs):
        try:
            return builder(self, *args, **kwargs)
        finally:
            self._finish_page()
    return build


class TargetRow(QWidget):
    """The "Target: [headset] Refresh" row at the top of a page, with room for
    a page's own buttons after it. Everything sits to the left; the row never
    stretches the dropdown across the page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(8)
        self.row.addStretch(1)

    def add(self, widget, stretch=0):
        self.row.insertWidget(self.row.count() - 1, widget, stretch)
        return widget


class ControlPanel(QMainWindow):
    """The panel window. Everything above the line "logic copied from the
    Tkinter panel" is Qt (the window, the pages, the log); everything below it
    is the Tk panel's own logic, unchanged."""

    def __init__(self, safe_preview=False):
        super().__init__()
        _dialog_parent_ref[:] = [self]
        # --screenshot: open the window for a picture only -- start no watchdog,
        # query nothing, save nothing.
        self._safe_preview = safe_preview
        self.setWindowTitle("CXVR Headset Control Panel (Qt)")
        self.setMinimumSize(800, 640)

        # The same state as the Tkinter panel's __init__.
        self.cfg = load_config()
        self.scripts_dir = materialize_scripts()
        self.log_queue: queue.Queue = queue.Queue()
        self.current_proc = None          # a one-shot foreground action, if any
        self._interrupt_attempts = 0      # tracks escalation: 1st click = graceful, 2nd = force-kill
        self.toggle_procs = {}            # name -> subprocess.Popen, for background watchdogs
        self.scrcpy_procs = {}            # device serial -> subprocess.Popen, for open screen-capture windows
        self.batch_scrcpy_procs = {}      # slot key -> subprocess.Popen, for batch-preview's currently-open windows
        self.batch_slot_threads = []      # one independent thread per rolling slot
        self.batch_cycle_stop_event = None
        self.batch_queue_lock = threading.Lock()      # guards the shared rolling device queue below
        self.batch_launch_lock = threading.Lock()     # ensures only one slot is mid-launch-setup at a time
        self._batch_device_list = []      # current known device list for the rolling queue
        self._batch_device_index = 0      # next position to hand out in that list
        self._batch_status_text = "Batch preview stopped."
        self.toggle_buttons = {}          # name -> ToggleSwitch, so re-entering a page shows correct state
        self.action_buttons = []          # one-shot buttons on the CURRENT page, disabled while busy
        # The built-in terminal's session state (the Tk panel set these up in _build_terminal).
        self._term = None
        self._terminal_unlocked = False   # opened from Testing for this session only
        self._term_pane_enabled = None

        self._build_ui()
        # The log pump. Its 100 ms tick is also what lets Python signal handlers
        # run at all while Qt's event loop is idle (see main()).
        self._pump_timer = QTimer(self)
        self._pump_timer.timeout.connect(self._poll_log_queue)
        self._pump_timer.start(LOG_PUMP_INTERVAL_MS)
        self._restore_window_state()
        self.show_menu_connect()
        self._update_terminal_visibility()
        self._append_log(f"[startup] Qt panel on Python {sys.version.split()[0]} ({sys.executable}), "
                         f"PySide6 {PYSIDE6_VERSION}, Qt {qVersion()}, platform {QApplication.platformName()}")
        old_package = str(self.cfg.get("package") or "").strip()
        if old_package and old_package != APP_PACKAGE:
            self._append_log(f"[settings] Your saved App package was {old_package!r}; the panel now always "
                             f"uses the built-in {APP_PACKAGE!r}. Change APP_PACKAGE at the top of the "
                             f"panel file if that's wrong.")
        if self._safe_preview:
            return
        self._warn_if_other_instance_running()

        # Headtracking watchdog runs by default -- no manual Start needed.
        # The script itself waits for at least one headset to connect before
        # doing anything, so it's safe to fire immediately at launch even
        # with nothing connected yet.
        self.action_toggle_ht_watchdog()

    # =================================================================== chrome
    def _build_ui(self):
        self._init_settings_vars()
        self.menu_title_var = StringVar(value="")
        self.status_vars = {key: StringVar(value="—") for key in ("connected", "confirmed", "failed", "total")}
        self.bg_tasks_var = StringVar(value="none running")

        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)
        top_layout.addWidget(self._build_strip())
        self.show_bar = QLabel("SHOW MODE IS ON — the overheat and black-screen watchdogs keep logging but "
                               "send nothing to any headset. Other watchdogs aren't affected.")
        self.show_bar.setObjectName("showBar")
        self.show_bar.setWordWrap(True)
        top_layout.addWidget(self.show_bar)
        self.setMenuWidget(top)
        _bind(self.show_bar, self.show_mode_var, lambda value: self._render_show_mode())
        self._render_show_mode()

        self._build_sidebar()
        self.page_scroll = QScrollArea()
        self.page_scroll.setObjectName("pageScroll")
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setCentralWidget(self.page_scroll)
        self.page = None
        self.page_layout = None
        self._build_docks()

    def _build_strip(self):
        """Status numbers, background tasks, Show Mode and the three always-available
        controls. Wide windows get one row; narrower ones (the show layout on half
        the laptop screen, or the 800 px minimum) get a compact two-row version."""
        self.strip = QFrame()
        self.strip.setObjectName("strip")
        outer = QVBoxLayout(self.strip)
        outer.setContentsMargins(14, 6, 12, 6)
        outer.setSpacing(4)
        self._strip_row1 = QHBoxLayout()
        self._strip_row1.setSpacing(12)
        self._strip_row2 = QHBoxLayout()
        self._strip_row2.setSpacing(8)
        outer.addLayout(self._strip_row1)
        outer.addLayout(self._strip_row2)

        self._brand = QWidget()
        brand = QVBoxLayout(self._brand)
        brand.setContentsMargins(0, 0, 6, 0)
        brand.setSpacing(0)
        wordmark = QLabel("CXVR")
        wordmark.setObjectName("wordmark")
        brand.addWidget(wordmark)
        sub = QLabel("Fleet control")
        sub.setObjectName("statCaption")
        brand.addWidget(sub)

        self._stats = QWidget()
        self._stats_grid = QGridLayout(self._stats)
        self._stats_grid.setContentsMargins(0, 0, 0, 0)
        self._stats_grid.setHorizontalSpacing(16)
        self._stats_grid.setVerticalSpacing(0)
        self._stat_cells = []
        for caption, key in (("connected & stable", "connected"), ("failed to confirm", "failed"),
                             ("fixed this run", "confirmed"), ("total fixed / connected", "total")):
            cell = StatCell(self.status_vars[key], caption)
            self._stat_cells.append(cell)
            if key == "failed":
                self.failed_value_label = cell

        self._tasks = QWidget()
        self._tasks_layout = QBoxLayout(QBoxLayout.Direction.TopToBottom, self._tasks)
        self._tasks_layout.setContentsMargins(0, 0, 0, 0)
        self._tasks_layout.setSpacing(2)
        tasks_caption = QLabel("Background tasks")
        tasks_caption.setObjectName("statCaption")
        self._tasks_layout.addWidget(tasks_caption)
        self._chips = ChipRow()
        self._tasks_layout.addWidget(self._chips, 1)
        _bind(self._chips, self.bg_tasks_var, self._render_bg_tasks)

        self._show_box = QWidget()
        show = QHBoxLayout(self._show_box)
        show.setContentsMargins(0, 0, 4, 0)
        show.setSpacing(7)
        self.show_mode_switch = VarSwitch(self.show_mode_var, command=self._toggle_show_mode, warn=True)
        self.show_mode_switch.setToolTip(SHOW_MODE_HELP)
        self._show_label = QLabel("Show mode")
        self._show_label.setObjectName("showModeLabel")
        self._show_label.setToolTip(SHOW_MODE_HELP)
        show.addWidget(self.show_mode_switch)
        show.addWidget(self._show_label)

        # Interrupt is ALWAYS enabled, deliberately never gated on state -- it's
        # the manual escape hatch for a hung script and must never be unusable.
        self.stop_all_btn = Button("Stop all tasks", self._stop_all_toggles, "stripBtn",
                                   tooltip="Stops every background watchdog this panel started.")
        self.interrupt_btn = Button("Interrupt script", self._interrupt_current, "stripBtn",
                                    tooltip="Interrupts the running one-shot script (and everything it started). "
                                            "Click again to force-kill it.")
        self.kill_adb_btn = Button("Kill ADB server", self.action_kill_adb_server, "stripBtn",
                                   tooltip="Restarts the local adb server. Every connection drops (asks first).")
        self._strip_wide = None
        self._apply_strip_mode(True)
        return self.strip

    def _apply_strip_mode(self, wide):
        if wide == self._strip_wide:
            return
        self._strip_wide = wide
        for row in (self._strip_row1, self._strip_row2):
            while row.count():
                row.takeAt(0)
        for i, cell in enumerate(self._stat_cells):
            self._stats_grid.removeWidget(cell)
            self._stats_grid.addWidget(cell, *((0, i) if wide else divmod(i, 2)))
            cell.set_compact(not wide)
        self._brand.setVisible(wide)
        self._tasks_layout.setDirection(QBoxLayout.Direction.TopToBottom if wide
                                        else QBoxLayout.Direction.LeftToRight)
        self._tasks_layout.setSpacing(2 if wide else 8)
        buttons = (self.stop_all_btn, self.interrupt_btn, self.kill_adb_btn)
        if wide:
            for widget, stretch in ((self._brand, 0), (self._stats, 0), (self._tasks, 1), (self._show_box, 0)):
                self._strip_row1.addWidget(widget, stretch)
        else:
            self._strip_row1.addWidget(self._stats)
            self._strip_row1.addStretch(1)
            self._strip_row1.addWidget(self._show_box)
            self._strip_row2.addWidget(self._tasks, 1)
        for button in buttons:
            self._strip_row1.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        self._strip_row1.setSpacing(12 if wide else 8)
        self.strip.layout().setSpacing(0 if wide else 3)

    def _render_bg_tasks(self, value):
        names = [] if value == "none running" else [n for n in str(value).split(", ") if n]
        self._chips.set_names([TASK_LABELS.get(name, name) for name in names])

    def _render_show_mode(self):
        on = bool(self.show_mode_var.get())
        self.strip.setProperty("showmode", on)
        self._show_label.setProperty("on", on)
        restyle(self.strip)
        restyle(self._show_label)
        self.show_bar.setVisible(on)

    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("sidebar")
        lay = QVBoxLayout(side)
        lay.setContentsMargins(0, 4, 0, 8)
        lay.setSpacing(1)
        self.nav_buttons = {}
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        for section, items in NAV_SECTIONS:
            head = small_caps(section, 7.5)
            head.setContentsMargins(16, 11, 0, 3)
            lay.addWidget(head)
            for key, text in items:
                button = QPushButton()
                button.setObjectName("nav")
                button.setCheckable(True)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setMinimumHeight(30)
                button.setAccessibleName(text)
                row = QHBoxLayout(button)
                row.setContentsMargins(14, 0, 10, 0)
                label = QLabel(text)
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                row.addWidget(label)
                row.addStretch(1)
                if key in PAGES_NOT_YET_PORTED:
                    later = QLabel("later")
                    later.setObjectName("navLater")
                    later.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                    row.addWidget(later)
                    button.setToolTip(f"Moves over to the Qt panel in phase {PAGES_NOT_YET_PORTED[key]} of the "
                                      f"port. Until then, use the Tkinter panel for it.")
                if key == "testing":
                    self._testing_badge = QLabel("")
                    self._testing_badge.setObjectName("navBadge")
                    self._testing_badge.setFixedHeight(18)
                    self._testing_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    self._testing_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                    row.addWidget(self._testing_badge)
                button.label_widget = label
                button.clicked.connect(lambda _checked=False, k=key: getattr(self, NAV_OPENERS[k])())
                self._nav_group.addButton(button)
                self.nav_buttons[key] = button
                lay.addWidget(button)
        lay.addStretch(1)
        panes = small_caps("Panes", 7.5)
        panes.setContentsMargins(16, 8, 0, 3)
        lay.addWidget(panes)
        self._pane_box = QVBoxLayout()
        self._pane_box.setContentsMargins(10, 0, 10, 4)
        self._pane_box.setSpacing(1)
        lay.addLayout(self._pane_box)
        note = QLabel("Qt port \u00b7 phase 1")
        note.setObjectName("sideNote")
        note.setToolTip("Pages marked \u201clater\u201d haven't moved to the Qt panel yet; they still run in the "
                        "Tkinter panel.")
        note.setContentsMargins(16, 6, 8, 0)
        lay.addWidget(note)
        side_scroll = QScrollArea()
        side_scroll.setObjectName("sideScroll")
        side_scroll.setWidget(side)
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QFrame.Shape.NoFrame)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side_scroll.setFixedWidth(SIDEBAR_WIDTH)

        self.sidebar_dock = QDockWidget("Navigation", self)
        self.sidebar_dock.setObjectName("sidebarDock")
        self.sidebar_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.sidebar_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self.sidebar_dock.setTitleBarWidget(QWidget())
        self.sidebar_dock.setWidget(side_scroll)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.sidebar_dock)
        # The sidebar runs the full height; the log/terminal panes sit to its right.
        self.setCorner(Qt.Corner.TopLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)

    def _set_nav_current(self, key):
        for name, button in self.nav_buttons.items():
            current = name == key
            button.setChecked(current)
            font = button.label_widget.font()
            font.setBold(current)
            button.label_widget.setFont(font)
            button.label_widget.setStyleSheet(f"color: {UI_ACCENT_DARK if current else UI_TEXT};")

    def _refresh_nav(self):
        self.nav_buttons["delete_video"].setVisible(self._is_tested("delete_video.delete"))
        pending = sum(1 for key in GATED_FEATURES if not self._is_tested(key))
        self._testing_badge.setText(str(pending))
        self._testing_badge.setVisible(pending > 0)

    def _build_docks(self):
        """The live log and the terminal are dock panes: tabbed along the bottom by
        default, or side by side, or floated onto another monitor. The arrangement
        is saved in the config (dock_state) when the panel closes."""
        self.setDockOptions(QMainWindow.DockOption.AnimatedDocks | QMainWindow.DockOption.AllowTabbedDocks
                            | QMainWindow.DockOption.AllowNestedDocks)
        for area in (Qt.DockWidgetArea.BottomDockWidgetArea, Qt.DockWidgetArea.RightDockWidgetArea,
                     Qt.DockWidgetArea.TopDockWidgetArea):
            self.setTabPosition(area, QTabWidget.TabPosition.North)
        areas = (Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
                 | Qt.DockWidgetArea.TopDockWidgetArea)
        features = (QDockWidget.DockWidgetFeature.DockWidgetClosable
                    | QDockWidget.DockWidgetFeature.DockWidgetMovable
                    | QDockWidget.DockWidgetFeature.DockWidgetFloatable)

        self.log_dock = QDockWidget("Live log", self)
        self.log_dock.setObjectName("logDock")
        self.log_dock.setAllowedAreas(areas)
        self.log_dock.setFeatures(features)
        self.log_text = QPlainTextEdit()
        self.log_text.setObjectName("console")
        self.log_text.setReadOnly(True)
        self.log_text.setUndoRedoEnabled(False)
        self.log_text.setMaximumBlockCount(LOG_MAX_LINES + 1)   # + the empty line after the last newline
        self.log_text.setFont(mono_font())
        self.log_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.log_text.setMinimumHeight(60)
        self.log_dock.setWidget(self.log_text)
        self.log_dock.setTitleBarWidget(
            DockTitle(self.log_dock, "Live log", extras=[Button("Clear", self._clear_log, "small")]))
        self._log_formats = {}
        for tag, colour in ((None, UI_CONSOLE_FG), ("fail", UI_LOG_FAIL), ("ok", UI_LOG_OK)):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(colour))
            self._log_formats[tag] = fmt

        self.term_dock = QDockWidget("Terminal", self)
        self.term_dock.setObjectName("terminalDock")
        self.term_dock.setAllowedAreas(areas)
        self.term_dock.setFeatures(features)
        holder = QFrame()
        holder.setObjectName("consoleNote")
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(14, 12, 14, 12)
        note = QLabel("The built-in terminal moves over to the Qt panel in phase 2 of the port. Until then, "
                      "use it in the Tkinter panel.")
        note.setWordWrap(True)
        holder_layout.addWidget(note)
        holder_layout.addStretch(1)
        self.term_dock.setWidget(holder)
        self.term_title = DockTitle(self.term_dock, "Terminal")
        self.term_dock.setTitleBarWidget(self.term_title)

        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.term_dock)
        self.tabifyDockWidget(self.log_dock, self.term_dock)
        self.log_dock.raise_()
        self.resizeDocks([self.log_dock], [190], Qt.Orientation.Vertical)

        self._pane_toggles = {}
        for dock, text in ((self.log_dock, "Live log"), (self.term_dock, "Terminal")):
            action = dock.toggleViewAction()   # tracks shown/closed, not which tab is in front
            toggle = QPushButton(text)
            toggle.setObjectName("paneToggle")
            toggle.setCheckable(True)
            toggle.setChecked(action.isChecked())
            toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            toggle.setToolTip(f"Show or hide the {text.lower()} pane")
            toggle.clicked.connect(lambda _checked=False, a=action: a.trigger())
            action.toggled.connect(toggle.setChecked)
            self._pane_box.addWidget(toggle)
            self._pane_toggles[dock.objectName()] = toggle

    # ------------------------------------------------------ window state
    def _restore_window_state(self):
        """Window size/position and the dock arrangement from the last session
        (config keys window_geometry and dock_state, which the Tkinter panel
        keeps but ignores)."""
        self._restored_dock_state = False
        restored_geometry = False
        geometry = self.cfg.get("window_geometry")
        if isinstance(geometry, str) and geometry:
            try:
                restored_geometry = self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
            except Exception:
                restored_geometry = False
        if not restored_geometry:
            self._apply_default_geometry()
        state = self.cfg.get("dock_state")
        if isinstance(state, str) and state:
            try:
                self._restored_dock_state = bool(
                    self.restoreState(QByteArray.fromBase64(state.encode("ascii")), WINDOW_STATE_VERSION))
            except Exception:
                self._restored_dock_state = False
        self.sidebar_dock.show()
        if not self._restored_dock_state:
            self.resizeDocks([self.log_dock], [max(170, int(self.height() * 0.28))], Qt.Orientation.Vertical)
        self._rescue_offscreen_docks()

    def _apply_default_geometry(self):
        width, height = 1280, 860
        screen = QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            width, height = min(width, area.width()), min(height, area.height())
            self.resize(max(width, 800), max(height, 640))
            self.move(area.x() + max(0, (area.width() - self.width()) // 2),
                      area.y() + max(0, (area.height() - self.height()) // 2))
        else:
            self.resize(width, height)

    def _rescue_offscreen_docks(self):
        """A pane floated onto a second monitor that isn't connected this time
        would otherwise reopen off-screen, out of reach. Dock it back instead."""
        screens = [s.availableGeometry() for s in QApplication.screens()]
        for dock in (self.log_dock, self.term_dock):
            if dock.isFloating() and not any(area.intersects(dock.geometry()) for area in screens):
                dock.setFloating(False)

    def _save_window_state(self):
        self.cfg["window_geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self.cfg["dock_state"] = bytes(self.saveState(WINDOW_STATE_VERSION).toBase64()).decode("ascii")
        save_config(self.cfg)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_strip_mode(self.width() >= STRIP_WIDE_MIN)

    def closeEvent(self, event):
        if not self._safe_preview:
            try:
                self._save_window_state()
            except Exception as e:   # never let a settings problem block closing
                print(f"[cxvr] couldn't save the window layout: {e}", file=sys.stderr)
        self._cleanup_subprocesses()
        event.accept()

    # ============================================================ page frame
    def _begin_page(self, nav_key, title):
        """Replaces the page area with a fresh, empty page and returns its layout.
        Every page is rebuilt when it's opened (so gating changes show at once);
        the old page is deleted once control has left it."""
        old = self.page_scroll.takeWidget()
        if old is not None:
            old.hide()
            old.deleteLater()
        self.action_buttons = []
        # Only switches on the page being built belong here -- the previous
        # page's are going away, and relabeling a deleted widget is an error.
        self.toggle_buttons = {}
        self._set_menu_title(title)
        page = QWidget()
        page.setObjectName("page")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(22, 14, 20, 18)
        outer.setSpacing(12)
        heading = QLabel(self.menu_title_var.get())
        heading.setObjectName("pageTitle")
        heading.setWordWrap(True)
        _bind(heading, self.menu_title_var, heading.setText)
        outer.addWidget(heading)
        content = QVBoxLayout()
        content.setSpacing(12)
        outer.addLayout(content)
        outer.addStretch(1)
        self.page = page
        self.page_layout = content
        self._set_nav_current(nav_key)
        self._refresh_nav()
        # Another panel instance (or the Tk panel) may have changed it meanwhile.
        self.show_mode_var.set(SHOW_MODE_FILE.exists())
        return content

    def _finish_page(self):
        if self.page is not None and self.page_scroll.widget() is not self.page:
            self.page_scroll.setWidget(self.page)

    # ============================================================ components
    def _card(self, title, right=None, help=None, layout=None):
        card = Card(title, right=right, help=help)
        (layout if layout is not None else self.page_layout).addWidget(card)
        return card

    def _mark_tested_button(self, key, refresh):
        return Button("Mark tested", lambda: self._mark_tested(key, refresh), kind="small")

    def _testing_banner(self, what, key, refresh, destination):
        self.page_layout.addWidget(TestingBanner(what, destination, lambda: self._mark_tested(key, refresh)))

    def _back_to_testing(self):
        self.page_layout.addWidget(Button("‹ Testing", self.show_menu_testing, kind="link"), 0,
                                   Qt.AlignmentFlag.AlignLeft)

    def _device_picker(self, layout, variable, label="Headset:", include_all=True, on_refresh=None):
        """A label, a read-only dropdown of connected headsets (plus ALL) and a
        Refresh button, added to `layout`; returns the dropdown. Every page that
        can target a single headset uses this, never a free-text box, so a typo
        can't send a command to the wrong place.

        The list starts with just the ALL entry and is filled in on Refresh:
        `adb devices` blocks, and running it while a page opens would make the
        whole window hitch every time."""
        layout.addWidget(field_label(label.rstrip(":")))
        values = [ALL_DEVICES_LABEL] if include_all else []
        combo = Combo(variable, values, chars=24)
        layout.addWidget(combo)
        if not variable.get() and values:
            variable.set(values[0])

        def refresh():
            devices, err = self._query_connected_devices()
            if err:
                messagebox.showerror("Refresh failed", f"Could not query adb devices: {err}")
                return
            new_values = ([ALL_DEVICES_LABEL] if include_all else []) + devices
            combo.configure(values=new_values)
            if variable.get() not in new_values:
                variable.set(new_values[0] if new_values else "")
            self._append_log(f"\n[devices] {len(devices)} connected: {', '.join(devices) or 'none'}\n")
            if on_refresh:
                on_refresh(devices)

        btn = Button("Refresh", refresh, kind="small")
        layout.addWidget(btn)
        self._register(btn)
        combo.refresh_button = btn
        return combo

    def _target_row(self, variable, note=None):
        """The same headset picker at the top of every page that can act on a
        single headset."""
        row = TargetRow()
        picker = QHBoxLayout()
        picker.setSpacing(8)
        self._device_picker(picker, variable, label="Target:")
        row.row.insertLayout(0, picker)
        if note:
            row.add(Caption(note), 1)
        self.page_layout.addWidget(row)
        return row

    def _toggle_row(self, layout, key, title, action, caption=None, caption_var=None,
                    settings=None, info=None, running=None):
        """One long-running task per row, ending in its Start/Stop switch.
        `action` is called with the switch, as the Tk panel's actions expect."""
        if running is None:
            running = bool(key) and key in self.toggle_procs
        row = ToggleRow(title, caption=caption, caption_var=caption_var, info=info, running=running)
        if settings is not None:
            settings(row.settings_layout)
        btn = ToggleSwitch(running=running, on_change=row.set_running)
        btn.configure(command=lambda: action(btn))
        row.set_switch(btn)
        layout.addWidget(row)
        if key:
            self.toggle_buttons[key] = btn
        return btn

    def _placeholder_page(self, nav_key, title, what, phase, back=False):
        """A page that hasn't been ported yet: says so, and where to find it."""
        lay = self._begin_page(nav_key, title)
        if back:
            self._back_to_testing()
        box = QFrame()
        box.setObjectName("placeholder")
        inner = QVBoxLayout(box)
        inner.setContentsMargins(16, 14, 16, 14)
        inner.setSpacing(6)
        name = QLabel(f"{what} isn't in the Qt panel yet")
        name.setObjectName("name")
        inner.addWidget(name)
        inner.addWidget(Caption(f"It moves over in phase {phase} of the port. Until then, use the Tkinter panel "
                                f"(cxvr_control_panel.py) for it — close this panel first, since the two "
                                f"shouldn't run at the same time. Both use the same settings."))
        lay.addWidget(box)

    # ================================================================ pages
    @_page
    def show_menu_connect(self):
        lay = self._begin_page("connect", "Connect / Reconnect Headsets")
        card = self._card("Connect headsets")
        row = QHBoxLayout()
        row.setSpacing(8)
        for label, cmd, kind in (("Normal Connect\nfixes broken or missing", self.action_connect, "primary"),
                                 ("Full Scan\nadds a subnet scan", self.action_full_scan, "big"),
                                 ("Purge & Reconnect All\ndisconnects all first", self.action_purge, "big")):
            row.addWidget(self._register(Button(label, cmd, kind)), 1)
        card.body.addLayout(row)

        opts = self._card("Options")
        opts.body.addWidget(Check("20 s tablet visual-check delay during the headtracking fix",
                                  self.visual_check_var, self._save_settings))
        opts.body.addWidget(Caption("Off by default."))
        return lay

    @_page
    def show_menu_heartbeat(self):
        self._begin_page("heartbeat", "Connection Heartbeat Monitor")
        card = self._card("Monitor")
        self._toggle_row(card.body, "heartbeat", "Connection Heartbeat", self.action_toggle_heartbeat,
                         caption="Polls every connected headset and logs reachability. Monitoring only — "
                                 "never sleeps, wakes or changes a headset.")

    @_page
    def show_menu_volume(self):
        lay = self._begin_page("volume", "Volume Control")
        last = self.cfg.get("last_volume_op") or "no volume operation run yet"
        self.volume_last_var = StringVar(value=f"Last requested: {last}")
        lay.addWidget(Caption(var=self.volume_last_var, variant="italic"))
        target = self._target_row(self.volume_target_var)
        target.add(self._register(Button("Check current volume", self.action_volume_check, kind="small")))

        presets = self._card("Presets")
        row = QHBoxLayout()
        row.setSpacing(8)
        for label, level in VOLUME_PRESETS:
            row.addWidget(self._register(Button(label, lambda lv=level, lbl=label: self.action_volume_preset(lv, lbl),
                                                kind="big")), 1)
        presets.body.addLayout(row)
        presets.body.addWidget(Caption("Each preset is measured, corrected and re-checked per headset, so a dropped "
                                       "keypress over wifi gets fixed instead of leaving one headset out of step."))

        exact = self._card("Exact level")
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(field_label("Level (0–15)"))
        row.addWidget(SpinEntry(self.volume_level_var, 0, 15))
        row.addWidget(self._register(Button("Set Volume", self.action_volume_set, kind="primary")))
        row.addSpacing(6)
        row.addWidget(Caption("An absolute level, not a reduction amount."), 1)
        exact.body.addLayout(row)

    @_page
    def show_menu_power(self):
        lay = self._begin_page("power", "Power Management")
        reboot_ok = self._is_tested("power.reboot")
        poweroff_ok = self._is_tested("power.poweroff")
        if not (reboot_ok or poweroff_ok):
            card = self._card("Power")
            card.body.addWidget(Caption("Reboot and Power Off are in Testing — open Testing in the sidebar.",
                                        variant="notice"))
            return lay
        self._target_row(self.power_target_var)
        card = self._card("Power")
        row = QHBoxLayout()
        row.setSpacing(8)
        if reboot_ok:
            button = self._register(Button("Reboot", self.action_reboot_all, kind="big"))
            button.setMinimumWidth(150)
            row.addWidget(button)
        if poweroff_ok:
            button = self._register(Button("Power Off", self.action_power_off_all, kind="danger"))
            button.setMinimumWidth(150)
            row.addWidget(button)
        row.addStretch(1)
        card.body.addLayout(row)
        if reboot_ok and poweroff_ok:
            note = ("Both ask for confirmation naming exactly which headsets are affected. Power Off can't be "
                    "undone remotely — each headset has to be turned back on by hand.")
        elif reboot_ok:
            note = ("Asks for confirmation naming exactly which headsets are affected. "
                    "Power Off is still in Testing — open Testing in the sidebar.")
        else:
            note = ("Asks for confirmation naming exactly which headsets are affected, and can't be undone "
                    "remotely. Reboot is still in Testing — open Testing in the sidebar.")
        card.body.addWidget(Caption(note))
        return lay

    @_page
    def show_menu_testing(self):
        lay = self._begin_page("testing", "Testing")
        lay.addWidget(Caption("Not yet confirmed on real headsets. Each works exactly as it will after testing "
                              "— this is only where you find it until then."))
        any_left = False
        for group, items in self._testing_items():
            pending = [item for item in items if not self._is_tested(item[0])]
            if not pending:
                continue
            any_left = True
            card = self._card(group)
            for i, (key, name, destination, opener) in enumerate(pending):
                if i:
                    card.body.addWidget(rule())
                row = QHBoxLayout()
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(8)
                text = QVBoxLayout()
                text.setSpacing(1)
                title = QLabel(name)
                title.setObjectName("name")
                text.addWidget(title)
                text.addWidget(Caption(f"Moves to {destination} once marked tested"))
                row.addLayout(text, 1)
                open_btn = Button("Open", opener)
                open_btn.setMinimumWidth(70)
                row.addWidget(open_btn, 0, Qt.AlignmentFlag.AlignVCenter)
                row.addWidget(Button("Mark tested", lambda k=key: self._mark_tested(k, self.show_menu_testing),
                                     kind="small"), 0, Qt.AlignmentFlag.AlignVCenter)
                holder = QWidget()
                holder.setLayout(row)
                holder.testing_key = key
                card.body.addWidget(holder)
        if not any_left:
            lay.addWidget(Caption("Nothing left to test — every gated feature has been marked tested and "
                                  "lives in its normal place now."))

    @_page
    def _render_testing_power(self):
        """Only the untested power actions, each with its own Mark tested --
        a separate page from the real Power page on purpose, so an untested
        action can never appear there before it's been confirmed."""
        lay = self._begin_page("testing", "Testing › Power Management")
        self._back_to_testing()
        pending = [(key, label, kind, cmd) for key, label, kind, cmd in (
            ("power.reboot", "Reboot", "big", self.action_reboot_all),
            ("power.poweroff", "Power Off", "danger", self.action_power_off_all))
            if not self._is_tested(key)]
        if not pending:
            lay.addWidget(Caption("Both are already marked tested — they're in Power Management now."))
            return
        self._target_row(self.power_target_var)
        for key, label, kind, cmd in pending:
            card = self._card(label, right=[self._mark_tested_button(key, self.show_menu_testing)])
            row = QHBoxLayout()
            row.setSpacing(12)
            button = self._register(Button(label, cmd, kind=kind))
            button.setMinimumWidth(150)
            row.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(Caption("Same confirmation as the real page, naming exactly which headsets are "
                                  "affected."), 1)
            card.body.addLayout(row)

    # Pages that arrive in later phases of the port.
    @_page
    def show_menu_sleepwake(self):
        self._placeholder_page("sleepwake", "Sleep / Wake Management", "Sleep / Wake", 2)

    @_page
    def show_menu_sync(self):
        self._placeholder_page("sync", "Content Sync", "Content Sync", 2)

    @_page
    def show_menu_delete_video(self):
        self._placeholder_page("delete_video", "Delete Video", "Delete Video", 2,
                               back=not self._is_tested("delete_video.delete"))

    @_page
    def show_menu_debug(self):
        self._placeholder_page("debug", "Debug Tools", "Debug Tools", 2)

    @_page
    def show_menu_screencap(self):
        self._placeholder_page("screencap", "Screen Capture", "Screen Capture", 3)

    @_page
    def _render_testing_sleepwake(self):
        self._placeholder_page("testing", "Testing › Sleep / Wake Management",
                               "Testing › Sleep / Wake", 2, back=True)

    @_page
    def _render_testing_snapshot(self):
        self._placeholder_page("testing", "Testing › Diagnostic Snapshot", "The Diagnostic Snapshot", 2,
                               back=True)

    @_page
    def _render_testing_terminal(self):
        self._placeholder_page("testing", "Testing › Terminal", "The terminal", 2, back=True)

    # ================================================================== log
    def _clear_log(self):
        self.log_text.clear()

    def _append_log(self, line):
        self._append_log_lines([line])

    def _append_log_lines(self, lines):
        """Adds lines exactly as the Tk log did (each one followed by a newline;
        a line containing FAIL in red, one saying confirmed / connect phase
        finished in green) and keeps the view at the bottom. Only the last
        LOG_MAX_LINES lines stay on screen."""
        _assert_main_thread("_append_log")
        cursor = QTextCursor(self.log_text.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.beginEditBlock()
        for line in lines:
            tag = None
            if "FAIL" in line:
                tag = "fail"
            elif "confirmed" in line.lower() or "connect phase finished" in line.lower():
                tag = "ok"
            cursor.insertText(line + "\n", self._log_formats[tag])
        cursor.endEditBlock()
        bar = self.log_text.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _poll_log_queue(self):
        """Runs every LOG_PUMP_INTERVAL_MS on the main thread: the only place
        worker-thread output reaches the window. Same handlers as the Tk panel's
        loop, but at most LOG_PUMP_MAX_ITEMS per tick (the rest waits for the
        next one), and runs of plain lines are added to the log in one go."""
        lines = []
        try:
            for _ in range(LOG_PUMP_MAX_ITEMS):
                item = self.log_queue.get_nowait()
                if item[0] == "line":
                    lines.append(item[1])
                    continue
                if lines:
                    self._append_log_lines(lines)
                    lines = []
                if item[0] == "done":
                    self._on_process_done(item[1])
                elif item[0] == "watchdog_summary":
                    self._parse_and_show_summary(item[1])
                elif item[0] == "batch_status":
                    self._batch_status_text = item[1]
                    if hasattr(self, "batch_status_var"):
                        self.batch_status_var.set(item[1])
                elif item[0] == "screencap_status_refresh":
                    if hasattr(self, "screencap_status_var"):
                        self.screencap_status_var.set(self._screencap_status_text())
                elif item[0] == "term_data":
                    if self._term is not None and item[1] == self._term["sid"]:
                        self._term_apply(item[2])
                elif item[0] == "term_exit":
                    self._term_on_exit(item[1], item[2])
        except queue.Empty:
            pass
        if lines:
            self._append_log_lines(lines)
        if TERMINAL_SUPPORTED and self._term is not None:
            self._term_update_echo_mask()
        self._refresh_toggle_state()

    # ============================================================= terminal
    # Phase 1 of the port: the Terminal pane exists (so its place in the saved
    # layout is kept) and appears exactly when the Tk terminal would, but the
    # terminal itself moves over in phase 2. No session is ever started here,
    # so the three hooks below are never reached yet.
    def _update_terminal_visibility(self):
        """The Terminal pane only exists once terminal.shell is marked tested, or
        after Show terminal on its Testing page for this session. Turning it off
        also ends any running session, so nothing keeps running unseen."""
        enabled = self._terminal_enabled()
        self._pane_toggles["terminalDock"].setVisible(enabled)
        if enabled:
            if self._term_pane_enabled is None and not self._restored_dock_state:
                self.term_dock.show()          # first run: there, but behind the live log
                self.log_dock.raise_()
            elif self._term_pane_enabled is False:
                self.term_dock.show()          # just switched on: bring it to the front
                self.term_dock.raise_()
        else:
            self.term_dock.hide()
            self._term_close_session()
        self._term_pane_enabled = enabled
        self._refresh_nav()

    def _term_apply(self, data):
        pass   # phase 2

    def _term_on_exit(self, sid, code):
        pass   # phase 2

    def _term_update_echo_mask(self):
        pass   # phase 2

    # ==================================================================
    # Everything below this line is logic copied from the Tkinter panel
    # (cxvr_control_panel.py), unchanged apart from the three substitutions
    # listed at the top of this file. The port kit's integrity test checks it.
    # ==================================================================
    def _set_menu_title(self, text):
        self.menu_title_var.set(text)

    def _refresh_toggle_state(self):
        """Called from the log-queue poll loop (so always on the main thread).
        A watchdog that exits on its own is removed from toggle_procs by its
        reader thread, which can't touch widgets -- this notices the change and
        brings the background-task label and any visible Start/Stop rows back
        in line with reality."""
        snapshot = tuple(sorted(list(self.toggle_procs)))
        if snapshot == getattr(self, "_last_toggle_snapshot", None):
            return
        self._last_toggle_snapshot = snapshot
        self._update_bg_tasks_label()
        for name, btn in list(self.toggle_buttons.items()):
            try:
                btn.configure(text="Stop" if name in self.toggle_procs else "Start")
            except RuntimeError:
                pass

    def _testing_items(self):
        """Every gated feature, grouped for the Testing hub, with where it
        moves once marked tested and which page opens it while untested."""
        return (
            ("Power Management", (
                ("power.reboot", "Reboot", "Power Management", self._render_testing_power),
                ("power.poweroff", "Power Off", "Power Management", self._render_testing_power))),
            ("Sleep / Wake Management", (
                ("sleepwake.overheat_watchdog", "Overheat Dismissal Watchdog", "Sleep / Wake",
                 self._render_testing_sleepwake),
                ("sleepwake.blackscreen_probe", "Black-Screen Probe", "Sleep / Wake",
                 self._render_testing_sleepwake))),
            ("Other", (
                ("delete_video.delete", "Delete Video", "the sidebar", self.show_menu_delete_video),
                ("debug.capture_snapshot", "Capture Diagnostic Snapshot", "Debug Tools",
                 self._render_testing_snapshot),
                ("terminal.shell", "Terminal", "the bottom of every screen",
                 self._render_testing_terminal))),
        )

    def show_menu_testing_category(self, category):
        openers = {"Power Management": self._render_testing_power,
                   "Sleep / Wake Management": self._render_testing_sleepwake,
                   "Delete Video": self.show_menu_delete_video,
                   "Debug Tools": self._render_testing_snapshot,
                   "Terminal": self._render_testing_terminal}
        openers.get(category, self.show_menu_testing)()

    def _sleepwake_target(self):
        return self._resolve_target(self.sleepwake_target_var)

    def _volume_target(self):
        return self._resolve_target(self.volume_target_var)

    def _init_settings_vars(self):
        """Just the tk variables -- no widgets here. Content-sync-specific
        fields (content dir / remote target) are only rendered
        inside the Content Sync submenu now, not globally; visual_check_var
        is rendered in the Connect submenu, also not globally."""
        self.content_dir_var = StringVar(value=self.cfg["content_dir"])
        self.remote_target_var = StringVar(value=self.cfg.get("remote_target", ""))
        self.visual_check_var = BooleanVar(value=self.cfg.get("visual_check", False))
        self.sync_clean_stale_var = BooleanVar(value=False)
        self.content_is_app_root_var = BooleanVar(value=self.cfg.get("content_is_app_root", False))
        self.sync_check_catalog_var = BooleanVar(value=False)
        self.sync_verify_hash_var = BooleanVar(value=False)
        self.sync_prune_var = BooleanVar(value=False)
        self.sync_keep_screen_on_var = BooleanVar(value=self.cfg.get("sync_keep_screen_on", False))
        self.sync_devices_var = StringVar(value="")
        self.sync_workers_var = StringVar(value=str(self.cfg.get("sync_workers", "6")))
        self.sync_min_free_mb_var = StringVar(value=str(self.cfg.get("sync_min_free_mb", "300")))
        self.sync_skip_power_config_var = BooleanVar(value=False)
        self.sync_skip_install_registration_var = BooleanVar(value=False)
        self.sync_connect_file_var = StringVar(value=self.cfg.get("sync_connect_file", ""))
        self.sync_state_dir_var = StringVar(value=self.cfg.get("sync_state_dir", ""))
        self.delete_video_selection_var = StringVar(value="")
        self.delete_video_device_var = StringVar(value="")
        self.delete_video_dry_run_var = BooleanVar(value=True)
        self.delete_video_skip_v3local_var = BooleanVar(value=False)
        self._delete_video_catalog = {}   # display label -> content ID, refreshed on menu show
        self.power_target_var = StringVar(value=ALL_DEVICES_LABEL)
        self.capture_device_var = StringVar(value=ALL_DEVICES_LABEL)
        self.capture_repeat_var = StringVar(value="1")
        self.capture_interval_var = StringVar(value="5")
        self.capture_screencap_var = BooleanVar(value=True)
        self.overheat_interval_var = StringVar(
            value=str(self.cfg.get("overheat_interval", "10")))
        self.overheat_arm_var = BooleanVar(value=self.cfg.get("overheat_arm", False))
        self.overheat_pattern_var = StringVar(
            value=self.cfg.get("overheat_pattern", DEFAULT_OVERHEAT_PATTERN))
        self.blackscreen_interval_var = StringVar(
            value=str(self.cfg.get("blackscreen_interval", "20")))
        self.blackscreen_arm_var = BooleanVar(value=self.cfg.get("blackscreen_arm", False))
        self.blackscreen_consecutive_var = StringVar(
            value=str(self.cfg.get("blackscreen_consecutive", "3")))
        self.blackscreen_recovery_var = StringVar(
            value=self.cfg.get("blackscreen_recovery", "wake"))
        self.show_mode_var = BooleanVar(value=SHOW_MODE_FILE.exists())
        self.group_batch_windows_var = BooleanVar(
            value=self.cfg.get("group_batch_windows", True))
        # Which gated features (see GATED_FEATURES) the operator has confirmed
        # against real hardware. Empty by default -- every feature listed
        # there starts out only reachable from the Testing menu.
        self.tested_features = set(self.cfg.get("tested_features", []))
        # Headset pickers and fields that used to be recreated every time their
        # menu opened -- created once here so a selection survives switching menus.
        self.sleepwake_target_var = StringVar(value=ALL_DEVICES_LABEL)
        self.volume_target_var = StringVar(value=ALL_DEVICES_LABEL)
        self.volume_level_var = StringVar(value="8")
        self.screencap_device_var = StringVar(value="")
        self._section_open = {}   # collapsible section key -> open?
        self.watchdog_verbose_var = BooleanVar(value=False)
        self.screencap_full_feed_var = BooleanVar(value=False)
        self.batch_interval_var = StringVar(value=str(self.cfg.get("batch_interval", "10")))
        self.screencap_titlebar_height_var = StringVar(
            value=str(self.cfg.get("titlebar_height", "30")))
        self.popup_watchdog_interval_var = StringVar(
            value=str(self.cfg.get("popup_watchdog_interval", "10")))
        self.diagnose_workers_var = StringVar(
            value=str(self.cfg.get("diagnose_workers", "6")))
        self.diagnose_filesize_var = StringVar(
            value=str(self.cfg.get("diagnose_filesize_mb", "300")))

    def _is_tested(self, feature_key):
        return feature_key in self.tested_features

    def _mark_tested(self, feature_key, refresh=None):
        """Records that the operator has confirmed a gated feature against
        real hardware, persists it, and re-renders whichever menu called this
        so the change is visible immediately -- the feature moves out of
        Testing and into its normal place without needing a restart."""
        self.tested_features.add(feature_key)
        self.cfg["tested_features"] = sorted(self.tested_features)
        self._save_settings()
        _, label = GATED_FEATURES.get(feature_key, ("", feature_key))
        self._append_log(f"\n[testing] marked tested: {label}\n")
        self._update_terminal_visibility()
        if refresh:
            refresh()

    def _unmark_tested(self, feature_key, refresh=None):
        """The reverse of _mark_tested -- sends a feature back to Testing.
        Offered next to Mark Tested wherever a feature lives once tested, in
        case something changes later and it needs re-validating."""
        self.tested_features.discard(feature_key)
        self.cfg["tested_features"] = sorted(self.tested_features)
        self._save_settings()
        _, label = GATED_FEATURES.get(feature_key, ("", feature_key))
        self._append_log(f"\n[testing] moved back to Testing: {label}\n")
        self._update_terminal_visibility()
        if refresh:
            refresh()

    @staticmethod
    def _resolve_target(variable):
        """Turns a device-picker selection into an optional serial: None means
        'all devices', which every targeted script expresses as simply not
        passing an argument."""
        value = (variable.get() or "").strip()
        if not value or value == ALL_DEVICES_LABEL:
            return None
        return value

    def _browse_content_dir(self):
        d = filedialog.askdirectory(title="Select content folder")
        if d:
            self.content_dir_var.set(d)
            self._save_settings()

    def _browse_connect_file(self):
        f = filedialog.askopenfilename(title="Select connect file (host:port lines)")
        if f:
            self.sync_connect_file_var.set(f)
            self._save_settings()

    def _browse_state_dir(self):
        d = filedialog.askdirectory(title="Select state folder")
        if d:
            self.sync_state_dir_var.set(d)
            self._save_settings()

    def _save_settings(self):
        self.cfg.update({
            "content_dir": self.content_dir_var.get(),
            "remote_target": self.remote_target_var.get(),
            "visual_check": self.visual_check_var.get(),
            "batch_interval": self.batch_interval_var.get(),
            "titlebar_height": self.screencap_titlebar_height_var.get(),
            "popup_watchdog_interval": self.popup_watchdog_interval_var.get(),
            "content_is_app_root": self.content_is_app_root_var.get(),
            "sync_keep_screen_on": self.sync_keep_screen_on_var.get(),
            "diagnose_workers": self.diagnose_workers_var.get(),
            "diagnose_filesize_mb": self.diagnose_filesize_var.get(),
            "sync_workers": self.sync_workers_var.get(),
            "sync_min_free_mb": self.sync_min_free_mb_var.get(),
            "sync_connect_file": self.sync_connect_file_var.get(),
            "sync_state_dir": self.sync_state_dir_var.get(),
            "overheat_interval": self.overheat_interval_var.get(),
            "overheat_arm": self.overheat_arm_var.get(),
            "overheat_pattern": self.overheat_pattern_var.get(),
            "blackscreen_interval": self.blackscreen_interval_var.get(),
            "blackscreen_arm": self.blackscreen_arm_var.get(),
            "blackscreen_consecutive": self.blackscreen_consecutive_var.get(),
            "blackscreen_recovery": self.blackscreen_recovery_var.get(),
            "group_batch_windows": self.group_batch_windows_var.get(),
        })
        save_config(self.cfg)

    def _script(self, filename):
        """Resolve a script filename against the materialized embedded-script
        cache -- re-materializing fresh from EMBEDDED_SCRIPTS every time this
        is called (cheap: ten small files), not just once at startup. This
        matters specifically for the watchdog: it's a long-lived background
        process, so if it were only ever launched from a copy written once at
        app startup, an app that's been running since before a code update
        could keep executing old watchdog logic indefinitely even after
        you've updated to a newer version of this file, with no obvious sign
        anything was stale. Re-materializing on every launch closes that gap:
        starting (or restarting) the watchdog always uses the script logic
        actually embedded in the app you're running right now."""
        materialize_scripts()
        path = self.scripts_dir / filename
        if not path.exists():
            messagebox.showerror("Missing script",
                                  f"Couldn't find {filename} in the embedded script cache:\n{self.scripts_dir}\n\n"
                                  "This shouldn't happen -- try restarting the app.")
            return None
        return str(path)

    def _toggle_show_mode(self):
        try:
            if self.show_mode_var.get():
                SHOW_MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
                SHOW_MODE_FILE.write_text(f"enabled {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                self._append_log("\n[show mode] ON -- automated corrective actions are suspended "
                                  "fleet-wide. Watchdogs keep monitoring and logging.\n")
            else:
                SHOW_MODE_FILE.unlink(missing_ok=True)
                self._append_log("\n[show mode] OFF -- automated corrective actions are allowed "
                                  "again (only for watchdogs that are actually armed).\n")
        except OSError as e:
            messagebox.showerror("Show mode", f"Couldn't update show mode: {e}")
            self.show_mode_var.set(SHOW_MODE_FILE.exists())

    def _load_video_catalog_from_content_dir(self):
        """Returns {display_label: video_id}, read entirely from the LOCAL content folder --
        no device access needed. Prefers files/App/*.v3 (the CMS catalog, present when
        --content-dir is a full device clone) to label each ID with its real title; falls back
        to bare content-ID folder names if no catalog is found locally (e.g. --content-dir was
        pointed directly at just the Video folder)."""
        content_dir_str = self.content_dir_var.get().strip()
        if not content_dir_str:
            return {}
        content_dir = Path(content_dir_str)
        if not content_dir.is_dir():
            return {}

        titles_by_id = {}
        app_dir = content_dir / "files" / "App"
        if app_dir.is_dir():
            catalog_matches = list(app_dir.glob("*.v3"))
            if catalog_matches:
                try:
                    raw = catalog_matches[0].read_text(encoding="utf-8-sig")
                    catalog = json.loads(raw)
                    for project in catalog.get("Project", []) or []:
                        vid = project.get("Video")
                        title = project.get("Title")
                        if vid and title:
                            titles_by_id[vid] = title
                except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                    pass   # fall back to bare IDs below -- this is a convenience label, not critical

        video_dir = content_dir / "files" / "Video"
        if not video_dir.is_dir():
            video_dir = content_dir   # content_dir may already BE the Video folder directly

        result = {}
        if video_dir.is_dir():
            for entry in sorted(video_dir.iterdir()):
                if entry.is_dir():
                    vid = entry.name
                    title = titles_by_id.get(vid)
                    label = f"{title} ({vid})" if title else vid
                    result[label] = vid
        return result

    def action_delete_video_refresh_catalog(self):
        self._delete_video_catalog = self._load_video_catalog_from_content_dir()
        video_labels = sorted(self._delete_video_catalog.keys())
        self.delete_video_combo.configure(values=video_labels)
        current = self.delete_video_selection_var.get()
        if video_labels and current not in video_labels:
            self.delete_video_selection_var.set(video_labels[0])
        elif not video_labels:
            self.delete_video_selection_var.set("")
        self._append_log(f"\n[delete video] {len(video_labels)} video(s) found in content folder\n")

    def action_delete_video_refresh_devices(self):
        devices, err = self._query_connected_devices()
        if err:
            messagebox.showerror("Refresh failed", f"Could not query adb devices: {err}")
            return
        values = ["ALL CONNECTED HEADSETS"] + devices
        self.delete_video_device_combo.configure(values=values)
        if self.delete_video_device_var.get() not in values:
            self.delete_video_device_var.set("ALL CONNECTED HEADSETS")
        self._append_log(f"\n[delete video] {len(devices)} connected device(s): {', '.join(devices) or 'none'}\n")

    def _delete_video_cmd(self):
        path = self._script("delete_video.py")
        if not path:
            return None

        label = self.delete_video_selection_var.get().strip()
        video_id = self._delete_video_catalog.get(label)
        if not video_id:
            messagebox.showerror("No video selected", "Choose a video from the list first (Refresh List "
                                                        "if the dropdown is empty).")
            return None

        device_choice = self.delete_video_device_var.get().strip()
        if not device_choice:
            messagebox.showerror("No headset selected", "Choose a headset, or ALL CONNECTED HEADSETS, first.")
            return None

        remote_target = self.remote_target_var.get().strip()
        package = APP_PACKAGE
        if not self._remote_target_matches_package(remote_target):
            return None
        if not remote_target:
            remote_target = f"/sdcard/Android/data/{package}"

        devices_arg = "ALL" if device_choice == "ALL CONNECTED HEADSETS" else device_choice

        cmd = [sys.executable, path, "--video-ids", video_id, "--devices", devices_arg,
               "--remote-target", remote_target]
        if package:
            cmd.extend(["--package", package])
        if self.delete_video_dry_run_var.get():
            cmd.append("--dry-run")
        if self.delete_video_skip_v3local_var.get():
            cmd.append("--skip-v3local-update")
        state_dir = self.sync_state_dir_var.get().strip()
        if state_dir:
            cmd.extend(["--state-dir", state_dir])
        return cmd, label, device_choice

    def action_delete_video(self):
        built = self._delete_video_cmd()
        if not built:
            return
        cmd, label, device_choice = built

        if not self.delete_video_dry_run_var.get():
            if not messagebox.askyesno(
                    "Confirm delete",
                    f"This will PERMANENTLY DELETE:\n\n  {label}\n\nfrom:\n\n  {device_choice}\n\n"
                    "This cannot be undone from this tool -- the video would need to be re-synced "
                    "from your source content folder afterward. Continue?"):
                return
        self._run_command(cmd)

    def action_capture_diagnostics(self):
        path = self._script("captureDiagnostics.sh")
        if not path:
            return
        repeat = self.capture_repeat_var.get().strip() or "1"
        interval = self.capture_interval_var.get().strip() or "5"
        if not repeat.isdigit() or int(repeat) < 1:
            messagebox.showerror("Invalid value", "Passes must be a positive whole number.")
            return
        if not interval.isdigit() or int(interval) < 1:
            messagebox.showerror("Invalid value", "Seconds between passes must be a positive whole number.")
            return

        cmd = ["bash", path, "--repeat", repeat, "--interval", interval,
               "--out-dir", str(SNAPSHOT_DIR)]
        target = self._resolve_target(self.capture_device_var)
        if target:
            cmd += ["--device", target]
        if not self.capture_screencap_var.get():
            cmd.append("--no-screencap")
        self._run_command(cmd)

    def _register(self, btn):
        self.action_buttons.append(btn)
        # A menu opened while a one-shot action is still running must come up
        # with its action buttons already disabled, same as the menu it replaced.
        if getattr(self, "current_proc", None) is not None:
            btn.configure(state="disabled")
        return btn

    def _toggle_label(self, name, start_text, stop_text):
        return stop_text if name in self.toggle_procs else start_text

    def _set_actions_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        for btn in self.action_buttons:
            btn.configure(state=state)

    def _run_command(self, cmd, on_done_parse_summary=False):
        if self.current_proc is not None:
            messagebox.showwarning("Busy", "Another action is already running -- wait for it to finish, "
                                            "or use Interrupt Running Script.")
            return
        self._set_actions_enabled(False)
        self._interrupt_attempts = 0
        self._append_log(f"\n$ {' '.join(cmd)}\n")

        # A content sync manipulates power state and saturates the AP. While
        # one is running, the watchdog daemons must not inject input -- a
        # recovery keyevent landing mid-push risks exactly the interrupted,
        # half-written transfer this project spent a long time hardening
        # against. A file (rather than in-process state) because the daemons
        # are separate processes.
        is_sync = any("sync_files.py" in str(part) for part in cmd)

        def worker():
            try:
                if is_sync:
                    try:
                        SYNC_IN_PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
                        SYNC_IN_PROGRESS_FILE.write_text(str(os.getpid()))
                    except OSError:
                        pass   # advisory only -- never block a sync over this
                proc = popen_in_own_group(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, bufsize=1, cwd=str(self.scripts_dir))
                self.current_proc = proc
                full_output = []
                if proc.stdout is not None:
                    for line in proc.stdout:
                        line = line.rstrip("\n")
                        full_output.append(line)
                        self.log_queue.put(("line", line))
                proc.wait()
                self.log_queue.put(("done", {"code": proc.returncode, "output": "\n".join(full_output),
                                              "parse_summary": on_done_parse_summary}))
            except FileNotFoundError as e:
                self.log_queue.put(("line", f"ERROR: {e}"))
                self.log_queue.put(("done", {"code": -1, "output": "", "parse_summary": False}))
            finally:
                self.current_proc = None
                if is_sync:
                    try:
                        SYNC_IN_PROGRESS_FILE.unlink(missing_ok=True)
                    except OSError:
                        pass

        threading.Thread(target=worker, daemon=True).start()

    def _interrupt_current(self):
        """Interrupt whichever one-shot script is currently running. Always
        clickable, even if nothing is running (just tells you so) -- this is
        the manual escape hatch for a hung script, so it must never itself
        be blocked by anything.

        Kills the WHOLE process group, not just the top-level script: a
        script that spawned a hung backgrounded `adb` call (e.g. talking to
        a headset that dropped off wifi) can otherwise leave that child
        holding the output pipe open forever even after the parent exits,
        which would leave the GUI stuck regardless of what signal we send.

        First click: graceful interrupt (Ctrl+C equivalent). If it's still
        running when clicked again, escalates to an unconditional kill --
        the priority here is guaranteeing you're never stuck, not being
        gentle about it.
        """
        if self.current_proc is None:
            messagebox.showinfo("Nothing running", "No script is currently running.")
            return
        proc = self.current_proc
        self._interrupt_attempts = getattr(self, "_interrupt_attempts", 0) + 1
        force = self._interrupt_attempts >= 2
        self._append_log(f"\n[sending {'FORCE KILL' if force else 'interrupt'} to running script "
                          f"and everything it spawned...]\n")
        kill_process_group(proc, force=force)
        if not force:
            self._append_log("[if it's still stuck, click Interrupt again to force-kill it]\n")

    def _on_process_done(self, info):
        self._set_actions_enabled(True)
        self._interrupt_attempts = 0
        self._append_log(f"[exit code {info['code']}]\n")
        if info.get("parse_summary"):
            self._parse_and_show_summary(info["output"])

    def _parse_and_show_summary(self, output):
        m = SUMMARY_PATTERNS["connected"].search(output)
        self.status_vars["connected"].set(m.group(1) if m else "—")
        m = SUMMARY_PATTERNS["confirmed"].search(output)
        self.status_vars["confirmed"].set(m.group(1) if m else "0")
        m = SUMMARY_PATTERNS["failed"].search(output)
        failed_val = m.group(1) if m else "0"
        self.status_vars["failed"].set(failed_val)
        if hasattr(self, "failed_value_label"):
            self.failed_value_label.configure(foreground="#c0392b" if failed_val not in ("0", "—") else "")
        m = SUMMARY_PATTERNS["total_fixed"].search(output)
        self.status_vars["total"].set(f"{m.group(1)} / {m.group(2)}" if m else "—")

    def _update_bg_tasks_label(self):
        if self.toggle_procs:
            self.bg_tasks_var.set(", ".join(sorted(self.toggle_procs.keys())))
        else:
            self.bg_tasks_var.set("none running")

    def _start_toggle(self, name, cmd, button=None, start_text="Start", stop_text="Stop", silent=False):
        if name in self.toggle_procs:
            kill_process_group(self.toggle_procs[name], force=False)
            del self.toggle_procs[name]
            if button:
                button.configure(text=start_text)
            self._append_log(f"\n[{name} watchdog stopped]\n")
            self._update_bg_tasks_label()
            return

        note = " (output suppressed -- watch the Status area instead)" if silent else ""
        self._append_log(f"\n$ (starting {name} watchdog in the background{note})\n")

        # Spawn synchronously on the main thread and register it in toggle_procs
        # right here -- not inside the background thread below. Popen itself
        # doesn't block (fork/exec only); only reading the process's output in
        # a loop does, which is the actual reason a background thread exists
        # at all. Registering it before starting that thread (and therefore
        # before _update_bg_tasks_label() runs a few lines down) guarantees the
        # Status area reflects reality immediately -- previously toggle_procs
        # was only set once the new thread got its first scheduling slice,
        # which reliably happens AFTER this function had already moved on and
        # updated the label, leaving it stuck on "none running" until some
        # unrelated later toggle action happened to refresh it.
        proc = popen_in_own_group(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, bufsize=1, cwd=str(self.scripts_dir))
        self.toggle_procs[name] = proc

        def worker():
            in_summary = False
            summary_lines = []
            if proc.stdout is not None:
                for line in proc.stdout:
                    line = line.rstrip("\n")
                    if silent:
                        # Don't forward regular lines to the visible log --
                        # just watch for a SUMMARY block and feed it to the
                        # status area instead, same as a one-shot run does.
                        if not in_summary and "SUMMARY" in line and line.count("=") > 10:
                            in_summary = True
                            summary_lines = [line]
                            continue
                        if in_summary:
                            summary_lines.append(line)
                            if line and set(line) == {"="}:  # closing delimiter line
                                self.log_queue.put(("watchdog_summary", "\n".join(summary_lines)))
                                in_summary = False
                                summary_lines = []
                            continue
                        # else: suppressed, not part of a summary block
                    else:
                        self.log_queue.put(("line", f"[{name}] {line}"))
            # process ended on its own (crashed or was killed outside our control)
            if self.toggle_procs.get(name) is proc:
                del self.toggle_procs[name]
                self.log_queue.put(("line", f"[{name} watchdog ended]"))

        threading.Thread(target=worker, daemon=True).start()
        if button:
            button.configure(text=stop_text)
        self._update_bg_tasks_label()

    def _stop_all_toggles(self):
        if not self.toggle_procs:
            return
        for name, proc in list(self.toggle_procs.items()):
            kill_process_group(proc, force=False)
            del self.toggle_procs[name]
            self._append_log(f"\n[{name} watchdog stopped]\n")
        for name, btn in self.toggle_buttons.items():
            try:
                btn.configure(text=btn.cget("text").replace("Stop", "Start"))
            except RuntimeError:
                pass  # button belongs to a menu that's no longer showing
        self._update_bg_tasks_label()

    def action_kill_adb_server(self):
        # NOTE: batch_scrcpy_procs is keyed by SLOT ("slot0", "slot1", ...),
        # not by device, since a slot shows different devices over time --
        # so listing its keys here would print meaningless labels. Report a
        # count for those instead of pretending they're device names.
        active = sorted(set(list(self.toggle_procs.keys()) + list(self.scrcpy_procs.keys())))
        batch_open = sum(1 for p in self.batch_scrcpy_procs.values() if p.poll() is None)
        msg = ("This kills the local adb server -- EVERY current connection drops immediately, "
               "not just a stuck one, including any running watchdogs, screen captures, and batch "
               "preview.")
        if active:
            msg += f"\n\nCurrently active: {', '.join(active)}"
        if batch_open:
            msg += f"\n\nBatch preview is running with {batch_open} open window(s)."
        msg += "\n\nYou'll need to reconnect (Connect / Full Scan) afterward. Continue?"
        if not messagebox.askyesno("Confirm Kill ADB Server", msg):
            return

        self._append_log("\n$ adb kill-server\n")
        try:
            result = subprocess.run(["adb", "kill-server"], capture_output=True, text=True, timeout=15)
            if result.stdout:
                self._append_log(result.stdout.rstrip())
            if result.stderr:
                self._append_log(result.stderr.rstrip())
            self._append_log(f"[adb kill-server exited with code {result.returncode}]\n")
        except Exception as e:
            self._append_log(f"[adb kill-server failed: {e}]\n")
            messagebox.showerror("Kill server failed", str(e))

    def _massconnect_cmd(self, *extra_args):
        path = self._script("massConnect.sh")
        if not path:
            return None
        cmd = ["bash", path]
        cmd.extend(extra_args)
        if self.visual_check_var.get():
            cmd.append("--visual-check")
        return cmd

    def action_connect(self):
        cmd = self._massconnect_cmd()
        if cmd:
            self._run_command(cmd, on_done_parse_summary=True)

    def action_full_scan(self):
        cmd = self._massconnect_cmd("--full-scan")
        if cmd:
            self._run_command(cmd, on_done_parse_summary=True)

    def action_purge(self):
        if not messagebox.askyesno("Confirm Purge",
                                    "This disconnects ALL current adb connections and does a full "
                                    "subnet rescan, ignoring the known-IPs cache. Continue?"):
            return
        cmd = self._massconnect_cmd("--purge")
        if cmd:
            self._run_command(cmd, on_done_parse_summary=True)

    def action_sleep_all(self):
        target = self._sleepwake_target()
        scope = target or "every connected headset"
        if not messagebox.askyesno("Confirm Sleep", f"This sleeps {scope} right now. Continue?"):
            return
        path = self._script("sleepAll.sh")
        if not path:
            return
        cmd = ["bash", path]
        if target:
            cmd.append(target)
        self._run_command(cmd)

    def action_wake_all(self):
        path = self._script("wakeAll.sh")
        if not path:
            return
        target = self._sleepwake_target()
        cmd = ["bash", path]
        if target:
            cmd.append(target)
        self._run_command(cmd)

    def action_screen_refresh(self):
        target = self._sleepwake_target()
        scope = target or "every connected headset"
        if not messagebox.askyesno("Confirm Sleep/Wake Cycle",
                                    f"This sleeps then wakes {scope} (manual headtracking fix). Continue?"):
            return
        path = self._script("screenRefresh.sh")
        if not path:
            return
        cmd = ["bash", path]
        if target:
            cmd.append(target)
        self._run_command(cmd)

    def action_toggle_stayawake(self, button):
        path = self._script("stayAwake.sh")
        if path:
            self._start_toggle("stayAwake", ["bash", path, "--parent-pid", str(os.getpid())], button,
                                "Start Stay-Awake Watchdog", "Stop Stay-Awake Watchdog")

    def action_toggle_keepalive(self, button):
        path = self._script("sync_files.py")
        if path:
            self._start_toggle("keepalive",
                                [sys.executable, path, "--keepalive", "--parent-pid", str(os.getpid())], button,
                                "Start Full Keepalive (reconnect+wake)", "Stop Full Keepalive")

    def action_toggle_ht_watchdog(self, button=None):
        path = self._script("massConnect.sh")
        if path:
            cmd = ["bash", path, "--watchdog", "--parent-pid", str(os.getpid())]
            if self.visual_check_var.get():
                cmd.append("--visual-check")
            verbose = getattr(self, "watchdog_verbose_var", None)
            self._start_toggle("htWatchdog", cmd, button,
                                "Start Headtracking Watchdog", "Stop Headtracking Watchdog",
                                silent=not (verbose and verbose.get()))

    def action_toggle_popup_watchdog(self, button):
        package = APP_PACKAGE
        path = self._script("popupWatchdog.sh")
        if path:
            interval = self.popup_watchdog_interval_var.get().strip() \
                if hasattr(self, "popup_watchdog_interval_var") else "10"
            if not interval.isdigit() or int(interval) <= 0:
                interval = "10"
            cmd = ["bash", path, "--package", package, "--interval", interval,
                   "--parent-pid", str(os.getpid())]
            self._save_settings()
            self._start_toggle("popupWatchdog", cmd, button,
                                "Start Popup/Crash Recovery Watchdog", "Stop Popup/Crash Recovery Watchdog")

    def action_toggle_overheat_watchdog(self, button):
        # Stopping doesn't need any of the validation below.
        if "overheatWatchdog" in self.toggle_procs:
            self._start_toggle("overheatWatchdog", None, button,
                                "Start Overheat Dismissal Watchdog", "Stop Overheat Dismissal Watchdog")
            return

        package = APP_PACKAGE
        path = self._script("overheatWatchdog.py")
        if not path:
            return

        pattern = self.overheat_pattern_var.get().strip() or DEFAULT_OVERHEAT_PATTERN
        interval = self.overheat_interval_var.get().strip()
        if not interval.isdigit() or int(interval) <= 0:
            interval = "10"

        if self.overheat_arm_var.get():
            if not messagebox.askyesno(
                    "Arm the overheat watchdog?",
                    "ARMED means this will send BACK to a headset whenever the pattern below "
                    f"matches:\n\n  {pattern}\n\n"
                    "Inside the app, BACK may exit playback -- so if this pattern matches anything "
                    "other than a real overheat prompt, it will interrupt a show.\n\n"
                    "If you haven't yet confirmed this pattern against a real overheat (via Debug "
                    "Tools > Diagnostic Snapshot), run it unarmed first instead.\n\n"
                    "Arm it anyway?"):
                return

        cmd = [sys.executable, path, "--package", package, "--interval", interval,
               "--match-pattern", pattern, "--state-dir", str(CONFIG_DIR),
               "--parent-pid", str(os.getpid())]
        if self.overheat_arm_var.get():
            cmd.append("--arm")
        self._save_settings()
        self._start_toggle("overheatWatchdog", cmd, button,
                            "Start Overheat Dismissal Watchdog", "Stop Overheat Dismissal Watchdog")

    def action_toggle_blackscreen_probe(self, button):
        if "blackScreenProbe" in self.toggle_procs:
            self._start_toggle("blackScreenProbe", None, button,
                                "Start Black-Screen Probe", "Stop Black-Screen Probe")
            return

        package = APP_PACKAGE
        path = self._script("blackScreenProbe.py")
        if not path:
            return

        interval = self.blackscreen_interval_var.get().strip()
        if not interval.isdigit() or int(interval) <= 0:
            interval = "20"
        consecutive = self.blackscreen_consecutive_var.get().strip()
        if not consecutive.isdigit() or int(consecutive) <= 0:
            consecutive = "3"
        recovery = self.blackscreen_recovery_var.get().strip() or "wake"

        if self.blackscreen_arm_var.get():
            if not messagebox.askyesno(
                    "Arm display-off recovery?",
                    f"ARMED means that after {consecutive} consecutive samples showing the display "
                    "powered OFF while your app is still in the foreground, this will send a "
                    f"{'wake keyevent' if recovery == 'wake' else 'sleep -> wake cycle'} to that "
                    "headset.\n\n"
                    "This case is deliberately narrow: it can't be confused with the black frames "
                    "between films, because those happen with the display ON.\n\n"
                    "Show Mode suspends this without stopping the probe. Arm it?"):
                return

        cmd = [sys.executable, path, "--package", package, "--interval", interval,
               "--consecutive", consecutive, "--recovery", recovery,
               "--state-dir", str(CONFIG_DIR), "--parent-pid", str(os.getpid())]
        if self.blackscreen_arm_var.get():
            cmd.append("--arm-display-off")
        self._save_settings()
        self._start_toggle("blackScreenProbe", cmd, button,
                            "Start Black-Screen Probe", "Stop Black-Screen Probe")

    def _record_volume_op(self, description):
        from datetime import datetime
        stamp = datetime.now().strftime("%H:%M:%S")
        text = f"{description} at {stamp}"
        self.cfg["last_volume_op"] = text
        save_config(self.cfg)
        if hasattr(self, "volume_last_var"):
            self.volume_last_var.set(f"Last requested: {text}")

    def action_volume_check(self):
        path = self._script("volumeNormalize.sh")
        if not path:
            return
        cmd = ["bash", path, "--check"]
        target = self._volume_target()
        if target:
            cmd.append(target)
        self._run_command(cmd)

    def action_volume_preset(self, level, label):
        target = self._volume_target()
        scope = target or "all connected headsets"
        if isinstance(level, int) and level <= 0:
            if not messagebox.askyesno("Confirm Mute",
                                        f"This will silence {scope}. Continue?"):
                return
        path = self._script("volumeNormalize.sh")
        if not path:
            return
        cmd = ["bash", path, "--set", str(level)]
        if target:
            cmd.append(target)
        self._run_command(cmd)
        self._record_volume_op(f"{label} ({scope})")

    def action_volume_set(self):
        path = self._script("volumeNormalize.sh")
        if not path:
            return
        level = self.volume_level_var.get().strip()
        if not level.isdigit() or not (0 <= int(level) <= 15):
            messagebox.showerror("Invalid level", "Level must be a whole number from 0 to 15.")
            return
        target = self._volume_target()
        scope = target or "all connected headsets"
        if int(level) == 0:
            if not messagebox.askyesno("Confirm Mute",
                                        f"This will silence {scope} (level 0). Continue?"):
                return
        cmd = ["bash", path, "--set", level]
        if target:
            cmd.append(target)
        self._run_command(cmd)
        self._record_volume_op(f"custom level {level} ({scope})")

    def action_reboot_all(self):
        target = self._resolve_target(self.power_target_var)
        scope = "EVERY connected headset" if target is None else f"headset {target}"
        if not messagebox.askyesno("Confirm Reboot", f"This reboots {scope}. Continue?"):
            return
        path = self._script("rebootAll.sh")
        if path:
            self._run_command(["bash", path] + ([target] if target else []))

    def action_power_off_all(self):
        target = self._resolve_target(self.power_target_var)
        scope = "EVERY connected headset" if target is None else f"headset {target}"
        which = "Each one" if target is None else "It"
        if not messagebox.askyesno("Confirm Power Off",
                                    f"This powers off {scope}. {which} will need to be "
                                    "turned back on by hand -- there is no remote way to power it "
                                    "back up. Continue?"):
            return
        path = self._script("powerOff.sh")
        if path:
            self._run_command(["bash", path] + ([target] if target else []))

    def action_toggle_heartbeat(self, button):
        path = self._script("heartbeatMaintain.sh")
        if path:
            self._start_toggle("heartbeat", ["bash", path, "--parent-pid", str(os.getpid())], button,
                                "Start Heartbeat Monitor", "Stop Heartbeat Monitor")

    def _remote_target_matches_package(self, remote_target):
        """A Remote target under /sdcard/Android/data/<some other package> would push content
        into one app's folders while the v3.local bookkeeping is written for APP_PACKAGE. Refuse
        that combination instead of guessing which one was meant."""
        match = re.search(r"/Android/data/([^/]+)", remote_target or "")
        if match and match.group(1) != APP_PACKAGE:
            messagebox.showerror(
                "Remote target is for a different app",
                f"Remote target points inside {match.group(1)}, but this panel is built for "
                f"{APP_PACKAGE}.\n\nFix Remote target in the Content Sync menu (or clear it to use "
                f"{APP_PACKAGE}'s own folders).")
            return False
        return True

    def _sync_cmd(self, *extra_args):
        path = self._script("sync_files.py")
        content_dir = self.content_dir_var.get().strip()
        package = APP_PACKAGE
        remote_target = self.remote_target_var.get().strip()
        if not path:
            return None
        if not content_dir:
            messagebox.showerror("Missing content folder",
                                  "Set a content folder in the Content Sync menu first.")
            return None
        if not self._remote_target_matches_package(remote_target):
            return None

        app_root = self.content_is_app_root_var.get()
        if app_root and remote_target:
            rt_normalized = remote_target.rstrip("/")
            if rt_normalized.endswith("/files/Video") or rt_normalized.endswith("/files/Media") or \
                    rt_normalized in ("files/Video", "files/Media"):
                messagebox.showerror(
                    "Remote target looks wrong for app-root mode",
                    "\"This is the app's own root folder\" is checked, but Remote target still "
                    "points at a files/Video or files/Media path specifically, not the app's root. "
                    "With both set this way, content would be pushed one level too deep and Prune "
                    "would see the real existing content as \"extra\" and delete it. Either uncheck "
                    "the app-root box, or change Remote target to the app's root "
                    f"(/sdcard/Android/data/{APP_PACKAGE}) or clear it to use the app's folders "
                    "automatically.")
                return None

        cmd = [sys.executable, path, "--content-dir", content_dir]
        package_already_passed = False
        if remote_target:
            cmd.extend(["--remote-target", remote_target])
        else:
            cmd.extend(["--package", package])
            package_already_passed = True

        if app_root:
            cmd.append("--content-is-app-root")
        if self.sync_verify_hash_var.get():
            cmd.append("--verify-hash")
        if self.sync_prune_var.get():
            cmd.append("--prune")
        if self.sync_keep_screen_on_var.get():
            cmd.append("--keep-screen-on")
        if self.sync_skip_power_config_var.get():
            cmd.append("--skip-power-config")
        if self.sync_skip_install_registration_var.get():
            cmd.append("--skip-install-registration")

        workers_str = self.sync_workers_var.get().strip()
        if workers_str:
            if not workers_str.isdigit() or int(workers_str) <= 0:
                messagebox.showerror("Invalid value", "Workers must be a positive whole number.")
                return None
            cmd.extend(["--workers", workers_str])

        min_free_str = self.sync_min_free_mb_var.get().strip()
        if min_free_str:
            if not min_free_str.isdigit():
                messagebox.showerror("Invalid value", "Min free space (MB) must be a whole number.")
                return None
            cmd.extend(["--min-free-mb", min_free_str])

        devices_str = self.sync_devices_var.get().strip()
        if devices_str:
            cmd.extend(["--devices", devices_str])

        connect_file = self.sync_connect_file_var.get().strip()
        if connect_file:
            cmd.extend(["--connect-file", connect_file])

        state_dir = self.sync_state_dir_var.get().strip()
        if state_dir:
            cmd.extend(["--state-dir", state_dir])

        needs_package = self.sync_clean_stale_var.get() or self.sync_check_catalog_var.get()
        if self.sync_clean_stale_var.get():
            cmd.append("--clean-stale-metadata")
        if self.sync_check_catalog_var.get():
            cmd.append("--check-catalog-ids")
        if needs_package and not package_already_passed:
            cmd.extend(["--package", package])
        cmd.extend(extra_args)
        return cmd

    def _confirm_prune_if_needed(self):
        if not self.sync_prune_var.get():
            return True
        return messagebox.askyesno(
            "Confirm delete",
            "The 'Also delete remote files not present locally' option is checked. This run will "
            "actually DELETE files from the device(s) that aren't in your local content folder "
            "(Headjack's own bookkeeping is never touched, only genuine extras). Continue?")

    def action_sync(self):
        if not self._confirm_prune_if_needed():
            return
        cmd = self._sync_cmd()
        if cmd:
            self._run_command(cmd)

    def action_sync_verify(self):
        if not self._confirm_prune_if_needed():
            return
        cmd = self._sync_cmd("--verify")
        if cmd:
            self._run_command(cmd)

    def action_sync_dryrun(self):
        cmd = self._sync_cmd("--dry-run")
        if cmd:
            self._run_command(cmd)

    def action_diagnose_bandwidth(self):
        workers_str = self.diagnose_workers_var.get().strip()
        filesize_str = self.diagnose_filesize_var.get().strip()
        if not workers_str.isdigit() or int(workers_str) <= 0:
            messagebox.showerror("Invalid value", "Max concurrency must be a positive whole number.")
            return
        if not filesize_str.isdigit() or int(filesize_str) <= 0:
            messagebox.showerror("Invalid value", "Test file size (MB) must be a positive whole number.")
            return

        path = self._script("sync_files.py")
        if not path:
            return
        self._save_settings()
        cmd = [sys.executable, path, "--diagnose-bandwidth",
               "--workers", workers_str, "--diagnose-file-size-mb", filesize_str]
        self._run_command(cmd)

    def action_toggle_debug_daemon(self):
        from datetime import datetime

        if getattr(self, "_debug_daemon_enabled", False):
            os.environ["PATH"] = getattr(self, "_debug_original_path", os.environ.get("PATH", ""))
            self._debug_daemon_enabled = False
            self._append_log(f"\n[ADB debug logging stopped. Log saved at: {self._debug_log_path}]\n")
            if hasattr(self, "debug_toggle_btn"):
                self.debug_toggle_btn.configure(text="Start ADB Traffic Debug Log")
            if hasattr(self, "debug_status_var"):
                self.debug_status_var.set("Not currently logging (off by default).")
            return

        real_adb = shutil.which("adb")
        if not real_adb:
            messagebox.showerror("adb not found", "Could not locate the real adb binary on PATH.")
            return

        wrapper_dir = CONFIG_DIR / "adb_debug_wrapper"
        wrapper_dir.mkdir(parents=True, exist_ok=True)
        log_dir = CONFIG_DIR / "adb_debug_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"adb_traffic_{datetime.now():%Y%m%d_%H%M%S}.log"

        # Transparent pass-through wrapper: log the exact invocation, then
        # exec the real adb with the same arguments, same stdin/stdout/
        # stderr -- callers see identical behavior to calling adb directly.
        wrapper_script = (
            "#!/bin/bash\n"
            f'echo "$(date \'+%Y-%m-%d %H:%M:%S.%3N\') PID=$$ PPID=$PPID CMD: adb $*" >> {shlex.quote(str(log_path))}\n'
            f'exec {shlex.quote(real_adb)} "$@"\n'
        )
        wrapper_path = wrapper_dir / "adb"
        wrapper_path.write_text(wrapper_script)
        wrapper_path.chmod(0o755)

        self._debug_original_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{wrapper_dir}{os.pathsep}{self._debug_original_path}"
        self._debug_daemon_enabled = True
        self._debug_log_path = log_path

        self._append_log(
            f"\n[ADB debug logging STARTED -- every adb call from this app (and any watchdog/toggle "
            f"started or restarted from now on) is being logged, unmodified, to:\n  {log_path}\n"
            f"Already-running background toggles won't be captured until you Stop and Start them again. "
            f"Disable this from the same button when done.]\n"
        )
        if hasattr(self, "debug_toggle_btn"):
            self.debug_toggle_btn.configure(text="Stop ADB Traffic Debug Log")
        if hasattr(self, "debug_status_var"):
            self.debug_status_var.set(f"Currently logging to: {log_path}")

    def _titlebar_height(self):
        """Parses the configurable title-bar-height field, falling back to
        a reasonable default (30px) if it's missing or not a valid number
        -- this varies by OS/window manager/theme, so it's tunable rather
        than a fixed assumption; this is just the safety net."""
        try:
            v = int(self.screencap_titlebar_height_var.get().strip())
            return v if v >= 0 else 30
        except (ValueError, AttributeError):
            return 30

    def _screencap_status_text(self):
        open_devices = [d for d, p in self.scrcpy_procs.items() if p.poll() is None]
        if open_devices:
            return f"Open capture window(s): {', '.join(open_devices)}"
        return "No capture windows currently open."

    def action_screencap_refresh(self):
        devices, err = self._query_connected_devices()
        if err:
            messagebox.showerror("Refresh failed", f"Could not query adb devices: {err}")
            return
        self.screencap_combo.configure(values=devices)
        current = self.screencap_device_var.get()
        if devices and current not in devices:
            self.screencap_device_var.set(devices[0])
        elif not devices:
            self.screencap_device_var.set("")
        self._append_log(f"\n[screen capture] {len(devices)} connected device(s): {', '.join(devices) or 'none'}\n")

    def _scrcpy_env(self, group=False):
        """Environment for a scrcpy launch. When group is set, forces a shared
        window class on every batch-preview window.

        Linux taskbars group windows by WM_CLASS (X11) / app_id (Wayland), not
        by window title -- so giving every batch window the same distinctive
        class is what makes them collapse into a single taskbar entry that can
        be hovered to pick an individual headset. scrcpy is SDL-based, so this
        is settable from the outside via SDL's own env vars; no scrcpy patch
        and no window-manager scripting needed.

        Both the X11 and Wayland variables are set because only the one
        matching the active session is read, and setting the other is
        harmless. On a desktop that ignores these entirely this is simply a
        no-op -- nothing breaks, the windows just don't group.
        """
        env = dict(os.environ)
        if group:
            env["SDL_VIDEO_X11_WMCLASS"] = "cxvr-batch"
            env["SDL_VIDEO_WAYLAND_WMCLASS"] = "cxvr-batch"
        return env

    def _launch_scrcpy_core(self, device, window_args=None):
        """Thread-safe: launches scrcpy for one device if not already open,
        tracks it in self.scrcpy_procs, forwards output via log_queue (safe
        from any thread, unlike messagebox/direct widget updates). Returns
        (ok: bool, error: str | None). Use this directly from background
        threads (batch preview, staggered Capture All); use _launch_scrcpy
        instead from main-thread button handlers, which adds dialogs."""
        existing = self.scrcpy_procs.get(device)
        if existing is not None and existing.poll() is None:
            return True, None

        scrcpy_path = shutil.which("scrcpy")
        if not scrcpy_path:
            return False, "scrcpy isn't installed or isn't on PATH."

        cmd = [scrcpy_path, "-s", device, "--port", SCRCPY_PORT_RANGE]
        if not self.screencap_full_feed_var.get():
            cmd += ["--crop", "1224:1232:0:104"]
        if window_args:
            cmd += window_args
        self.log_queue.put(("line", f"$ {' '.join(cmd)}"))
        try:
            proc = popen_in_own_group(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, bufsize=1, env=self._scrcpy_env(group=False))
        except Exception as e:
            return False, str(e)
        self.scrcpy_procs[device] = proc

        def worker():
            if proc.stdout is not None:
                for line in proc.stdout:
                    self.log_queue.put(("line", f"[scrcpy:{device}] {line.rstrip(chr(10))}"))
            if self.scrcpy_procs.get(device) is proc:
                del self.scrcpy_procs[device]
                self.log_queue.put(("line", f"[scrcpy:{device}] window closed"))

        threading.Thread(target=worker, daemon=True).start()
        return True, None

    def _launch_scrcpy_and_wait_ready(self, device, window_args=None, ready_timeout=8,
                                       track_dict=None, quiet=False, track_key=None):
        """Thread-safe, like _launch_scrcpy_core, but BLOCKS the calling
        thread until this device's connection is actually confirmed
        established (scrcpy's own "[server] INFO: Device:" line appearing
        in its output) or ready_timeout elapses. Used for staggered batch
        launches (Capture All / Batch Preview) INSTEAD of a blind fixed
        delay: a fixed sleep can't tell a fast, successful connection from
        a slow/stuck one, so it either wastes time waiting after everyone's
        already ready, or doesn't wait long enough and lets several
        instances race to set up their adb tunnel at the same time (which
        is what caused failures even after increasing the delay). Waiting
        for actual confirmation serializes only the genuinely sensitive
        setup window, not a guessed duration.

        track_dict lets callers use their own tracking dict (Batch Preview
        uses self.batch_scrcpy_procs, kept separate from self.scrcpy_procs
        so the two features can never interfere with each other) --
        defaults to self.scrcpy_procs. track_key lets callers track by
        something other than the device serial -- Batch Preview's rolling
        per-slot design has a stable SLOT identity showing a DIFFERENT
        device over time, so it tracks by slot key instead of device;
        defaults to device (the original per-device tracking used by
        Connect/Capture All) when not given. quiet=True skips forwarding
        output to the log (Batch Preview cycles repeatedly and was
        deliberately designed to stay quiet) while still watching for the
        readiness marker internally.

        Note: the specific marker string is what this scrcpy version (3.3.4,
        confirmed from real logs) prints on success -- if a future scrcpy
        version changes its output format, this stops recognizing success
        and every device will just wait out the full timeout instead
        (slower, but not broken -- output still streams to the log either
        way, unless quiet=True).

        Returns (ok: bool, ready: bool, error: str | None). ok=False only
        on outright launch failure. ready=False means we gave up waiting
        without seeing confirmation (the device may still connect after
        we've moved on -- we just stop blocking the next launch on it)."""
        if track_dict is None:
            track_dict = self.scrcpy_procs
        if track_key is None:
            track_key = device

        existing = track_dict.get(track_key)
        if existing is not None and existing.poll() is None:
            return True, True, None

        scrcpy_path = shutil.which("scrcpy")
        if not scrcpy_path:
            return False, False, "scrcpy isn't installed or isn't on PATH."

        cmd = [scrcpy_path, "-s", device, "--port", SCRCPY_PORT_RANGE]
        if not self.screencap_full_feed_var.get():
            cmd += ["--crop", "1224:1232:0:104"]
        if window_args:
            cmd += window_args
        if not quiet:
            self.log_queue.put(("line", f"$ {' '.join(cmd)}"))
        try:
            proc = popen_in_own_group(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                env=self._scrcpy_env(group=(track_dict is not self.scrcpy_procs
                                             and self.group_batch_windows_var.get())))
        except Exception as e:
            return False, False, str(e)
        track_dict[track_key] = proc

        ready_event = threading.Event()

        def worker():
            if proc.stdout is not None:
                for line in proc.stdout:
                    if not quiet:
                        self.log_queue.put(("line", f"[scrcpy:{device}] {line.rstrip(chr(10))}"))
                    if "[server] INFO: Device:" in line:
                        ready_event.set()
            if track_dict.get(track_key) is proc:
                del track_dict[track_key]
                if not quiet:
                    self.log_queue.put(("line", f"[scrcpy:{device}] window closed"))

        threading.Thread(target=worker, daemon=True).start()
        became_ready = ready_event.wait(timeout=ready_timeout)
        return True, became_ready, None

    def _launch_scrcpy(self, device, window_args=None, quiet_if_already_open=False):
        """Main-thread only -- shows error/info dialogs on top of the
        thread-safe core. Shared by both the single Connect button and
        Capture All's initial checks, so Close All (which only ever touches
        self.scrcpy_procs) correctly covers windows opened either way, and
        never anything opened outside this app. Returns True if a window is
        open for this device afterward (whether newly launched or already
        running), False on failure."""
        existing = self.scrcpy_procs.get(device)
        already_open = existing is not None and existing.poll() is None
        if already_open and not quiet_if_already_open:
            messagebox.showinfo("Already open", f"A capture window for {device} is already open.")
            return True

        ok, err = self._launch_scrcpy_core(device, window_args)
        if not ok:
            if err and "not installed" in err:
                messagebox.showerror("scrcpy not found",
                                      "scrcpy isn't installed or isn't on PATH. Install it from "
                                      "https://github.com/Genymobile/scrcpy and try again.")
            else:
                messagebox.showerror("Failed to launch scrcpy", err or "unknown error")
        return ok

    def action_screencap_connect(self):
        device = self.screencap_device_var.get().strip()
        if not device:
            messagebox.showerror("No headset selected", "Select a headset from the dropdown first "
                                                          "(or click Refresh Device List).")
            return
        self._launch_scrcpy(device)
        if hasattr(self, "screencap_status_var"):
            self.screencap_status_var.set(self._screencap_status_text())

    @staticmethod
    def _query_connected_devices():
        """Returns (devices, error). devices is a list of serials in
        'device' state; error is None on success or a message on failure.
        Shared by Capture All and the batch-preview loop so both always
        agree on what's currently connected."""
        try:
            result = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=10)
        except Exception as e:
            return [], str(e)
        devices = []
        for line in result.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices, None

    def action_screencap_connect_all(self):
        devices, err = self._query_connected_devices()
        if err:
            messagebox.showerror("Refresh failed", f"Could not query adb devices: {err}")
            return
        if not devices:
            messagebox.showinfo("No headsets", "No connected headsets found.")
            return
        if len(devices) > SCREENCAP_MAX_PARALLEL:
            messagebox.showwarning(
                "Too many headsets for Capture All",
                f"{len(devices)} headsets are connected. Capture All has no way to group or cycle "
                f"them, so opening all of them at once isn't practical past {SCREENCAP_MAX_PARALLEL} "
                f"-- for a fleet this size, use Batch Preview instead, which opens "
                f"{SCREENCAP_MAX_PARALLEL} at a time, tiled and spaced properly, and automatically "
                f"cycles to the next group after your chosen interval.")
            return
        if not shutil.which("scrcpy"):
            messagebox.showerror("scrcpy not found",
                                  "scrcpy isn't installed or isn't on PATH. Install it from "
                                  "https://github.com/Genymobile/scrcpy and try again.")
            return

        layout = compute_tile_layout(len(devices), title_bar_height=self._titlebar_height())
        self._save_settings()   # keep the tuned title-bar height across restarts
        self._append_log(f"\n[screen capture] launching {len(devices)} window(s), one at a time, "
                          f"waiting for each to confirm before starting the next, tiled across a "
                          f"1920x1080 layout...\n")

        def worker():
            for i, (device, (x, y, w, h)) in enumerate(zip(devices, layout)):
                if i > 0:
                    time.sleep(SCRCPY_INTER_LAUNCH_GAP)
                window_args = ["--window-x", str(x), "--window-y", str(y),
                                "--window-width", str(w), "--window-height", str(h),
                                "--window-title", f"scrcpy - {device}"]
                ok, ready, launch_err = self._launch_scrcpy_and_wait_ready(
                    device, window_args, ready_timeout=SCRCPY_READY_TIMEOUT)
                if not ok:
                    self.log_queue.put(("line", f"[screen capture] failed to launch for {device}: {launch_err}"))
                elif not ready:
                    self.log_queue.put(("line", f"[screen capture] {device} didn't confirm connection "
                                                 f"within {SCRCPY_READY_TIMEOUT}s -- continuing to the next "
                                                 f"device anyway"))
            self.log_queue.put(("screencap_status_refresh", None))

        threading.Thread(target=worker, daemon=True).start()

    def action_screencap_close_all(self):
        batch_was_running = bool(self.batch_slot_threads) and any(t.is_alive() for t in self.batch_slot_threads)
        if not self.scrcpy_procs and not batch_was_running and not self.batch_scrcpy_procs:
            messagebox.showinfo("Nothing open", "No capture windows opened by this app are currently open.")
            return
        if batch_was_running:
            self._stop_batch_cycle_thread()
        for device, proc in list(self.scrcpy_procs.items()):
            kill_process_group(proc, force=True)
        self.scrcpy_procs.clear()
        for device, proc in list(self.batch_scrcpy_procs.items()):
            kill_process_group(proc, force=True)
        self.batch_scrcpy_procs.clear()
        self._append_log("\n[screen capture] closed all script-opened capture window(s), including batch "
                          "preview if it was running (any manually-opened scrcpy session was left alone)\n")
        if hasattr(self, "screencap_status_var"):
            self.screencap_status_var.set(self._screencap_status_text())
        self._batch_status_text = "Batch preview stopped."
        if hasattr(self, "batch_status_var"):
            self.batch_status_var.set(self._batch_status_text)
        if hasattr(self, "batch_preview_btn"):
            self.batch_preview_btn.configure(text="Start Batch Preview")

    def _stop_batch_cycle_thread(self):
        """Signal every slot loop to stop and wait for them all to actually
        exit, WITHOUT touching batch_scrcpy_procs itself -- callers decide
        separately whether to also close currently-open windows. A slot
        that's mid-launch (waiting on its own confirm-or-timeout) won't
        interrupt early, so this can take up to SCRCPY_READY_TIMEOUT to
        return -- bounded, not indefinite, since batch_launch_lock ensures
        only one slot can be in that state at a time."""
        if self.batch_cycle_stop_event is not None:
            self.batch_cycle_stop_event.set()
        for t in self.batch_slot_threads:
            t.join(timeout=SCRCPY_READY_TIMEOUT + 3)
        self.batch_slot_threads = []
        self.batch_cycle_stop_event = None

    def _next_batch_device(self, exclude=None):
        """Hand out the next device in round-robin order from a shared
        queue, thread-safe so multiple slots can pull from it concurrently.
        Skips any device in `exclude` (devices actively shown in OTHER
        slots right now) so the same headset can never end up displayed in
        two slots at once -- a real risk whenever the device count isn't a
        clean multiple of the slot count, since a fast-cycling slot could
        otherwise wrap the queue around onto a device another slot is still
        showing. Refreshes the device list (adapting to a changed fleet)
        each time the queue wraps around. Returns None if nothing is
        connected, or every device in a full pass is already shown
        elsewhere (only possible when device count <= slot count, which
        action_batch_preview_toggle already prevents by capping slots at
        min(SCREENCAP_MAX_PARALLEL, device count))."""
        exclude = exclude or set()
        with self.batch_queue_lock:
            examined = 0
            max_examined = None
            while True:
                if not self._batch_device_list or self._batch_device_index >= len(self._batch_device_list):
                    devices, _err = self._query_connected_devices()
                    self._batch_device_list = devices
                    self._batch_device_index = 0
                    if not self._batch_device_list:
                        return None
                if max_examined is None:
                    max_examined = len(self._batch_device_list)
                if examined >= max_examined:
                    return None
                device = self._batch_device_list[self._batch_device_index]
                self._batch_device_index += 1
                examined += 1
                if device not in exclude:
                    return device

    def _update_batch_status(self, slot_occupants):
        shown = [f"{d}" for d in slot_occupants.values() if d]
        if shown:
            status = f"Showing ({len(shown)} slot(s)): {', '.join(shown)}"
        else:
            status = "Batch preview running -- no active slots yet."
        self.log_queue.put(("batch_status", status))

    def _batch_slot_loop(self, slot_key, x, y, w, h, interval, stop_event, slot_occupants):
        """Runs in its own background thread, one per rolling slot,
        completely independent of every other slot's timing. Each pass:
        pull the next device from the shared queue, launch it at this
        slot's fixed position (serialized against other slots via
        batch_launch_lock so only one adb tunnel is ever being set up at a
        time -- the thing that actually caused failures before), wait out
        the swap interval STARTING FROM when this slot settled (confirmed
        ready, or gave up waiting -- either way, the timer starts once we
        stop blocking on setup), then close and loop. Never synchronizes
        with the other slots' schedules -- that's the whole point: a slot
        swaps on its own clock, not in lockstep with the rest."""
        while not stop_event.is_set():
            # Skip devices busy in another slot, AND devices the operator
            # already has open manually via Connect / Capture All. Without
            # the latter, batch preview could open a SECOND scrcpy instance
            # for a device that already has a manual window -- and when
            # batch closed its own copy on schedule, that tore down the
            # shared adb tunnel out from under the manual window too,
            # making manually-opened captures appear to close themselves on
            # batch preview's timer.
            manually_open = {d for d, p in self.scrcpy_procs.items() if p.poll() is None}
            currently_elsewhere = {d for k, d in slot_occupants.items() if k != slot_key and d}
            device = self._next_batch_device(exclude=currently_elsewhere | manually_open)
            if device is None:
                self.log_queue.put(("line", f"[batch preview] {slot_key}: no headset available "
                                             f"(all connected ones are already shown elsewhere or open "
                                             f"manually) -- waiting"))
                if stop_event.wait(2):
                    return
                continue

            window_args = ["--window-x", str(x), "--window-y", str(y),
                            "--window-width", str(w), "--window-height", str(h),
                            "--window-title", f"scrcpy - {device}"]

            with self.batch_launch_lock:
                if stop_event.is_set():
                    return
                ok, ready, err = self._launch_scrcpy_and_wait_ready(
                    device, window_args, ready_timeout=SCRCPY_READY_TIMEOUT,
                    track_dict=self.batch_scrcpy_procs, quiet=True, track_key=slot_key)
                # Re-check stop WHILE STILL HOLDING THE LOCK. A launch can
                # block for up to SCRCPY_READY_TIMEOUT, which is long enough
                # for a stop (Close All / toggle off / app close) to have
                # signaled, joined with a timeout, and already cleared
                # batch_scrcpy_procs -- in which case the window we just
                # registered would be left orphaned with nothing tracking
                # it. Tear it down here instead of leaking it.
                if stop_event.is_set():
                    proc = self.batch_scrcpy_procs.pop(slot_key, None)
                    if proc is not None:
                        kill_process_group(proc, force=True)
                    slot_occupants[slot_key] = None
                    return

            if not ok:
                self.log_queue.put(("line", f"[batch preview] {slot_key}: failed to launch {device}: {err}"))
                slot_occupants[slot_key] = None
                if stop_event.wait(2):
                    return
                continue
            if not ready:
                self.log_queue.put(("line", f"[batch preview] {slot_key}: {device} didn't confirm within "
                                             f"{SCRCPY_READY_TIMEOUT}s -- showing anyway"))

            slot_occupants[slot_key] = device
            self._update_batch_status(slot_occupants)

            if stop_event.wait(interval):
                proc = self.batch_scrcpy_procs.pop(slot_key, None)
                if proc is not None:
                    kill_process_group(proc, force=True)
                return

            proc = self.batch_scrcpy_procs.pop(slot_key, None)
            if proc is not None:
                kill_process_group(proc, force=True)
            slot_occupants[slot_key] = None

    def action_batch_preview_toggle(self):
        if self.batch_slot_threads and any(t.is_alive() for t in self.batch_slot_threads):
            self._stop_batch_cycle_thread()
            for proc in list(self.batch_scrcpy_procs.values()):
                kill_process_group(proc, force=True)
            self.batch_scrcpy_procs.clear()
            self._append_log("\n[batch preview] stopped, closed open window(s)\n")
            self._batch_status_text = "Batch preview stopped."
            if hasattr(self, "batch_status_var"):
                self.batch_status_var.set(self._batch_status_text)
            if hasattr(self, "batch_preview_btn"):
                self.batch_preview_btn.configure(text="Start Batch Preview")
            return

        interval_str = self.batch_interval_var.get().strip() if hasattr(self, "batch_interval_var") else "10"
        if not interval_str.isdigit() or int(interval_str) <= 0:
            messagebox.showerror("Invalid interval", "Swap time must be a positive whole number of seconds.")
            return
        interval = int(interval_str)
        # Persist here (rather than on every keystroke) -- by this point the
        # value is validated, and the title bar height is worth saving at the
        # same time since both are tuned once per machine and shouldn't reset
        # on the next launch.
        self._save_settings()

        if not shutil.which("scrcpy"):
            messagebox.showerror("scrcpy not found",
                                  "scrcpy isn't installed or isn't on PATH. Install it from "
                                  "https://github.com/Genymobile/scrcpy and try again.")
            return

        devices, err = self._query_connected_devices()
        if err:
            messagebox.showerror("Refresh failed", f"Could not query adb devices: {err}")
            return
        if not devices:
            messagebox.showinfo("No headsets", "No connected headsets found.")
            return

        # Devices with a manual capture window open are off-limits to batch
        # preview (see _batch_slot_loop), so size the slot count against
        # what's actually available to it -- otherwise slots would spin
        # logging "no headset available" instead of showing anything.
        manually_open = {d for d, p in self.scrcpy_procs.items() if p.poll() is None}
        available = [d for d in devices if d not in manually_open]
        if not available:
            messagebox.showinfo(
                "No headsets available",
                f"All {len(devices)} connected headset(s) already have a capture window open manually.\n\n"
                f"Batch Preview skips those to avoid opening a second window for the same headset, so "
                f"there's nothing left for it to show. Close some manually-opened windows first "
                f"(Close All Script-Opened Windows), or connect more headsets.")
            return

        num_slots = min(SCREENCAP_MAX_PARALLEL, len(available))
        layout = compute_tile_layout(num_slots, region_w=960, region_h=1080, offset_x=960, offset_y=0,
                                      title_bar_height=self._titlebar_height())

        self._batch_device_list = devices
        self._batch_device_index = 0
        self.batch_cycle_stop_event = threading.Event()
        slot_occupants = {}
        self.batch_slot_threads = []
        for i, (x, y, w, h) in enumerate(layout):
            slot_key = f"slot{i}"
            slot_occupants[slot_key] = None
            t = threading.Thread(
                target=self._batch_slot_loop,
                args=(slot_key, x, y, w, h, interval, self.batch_cycle_stop_event, slot_occupants),
                daemon=True)
            t.start()
            self.batch_slot_threads.append(t)

        self._append_log(f"\n[batch preview] started, {num_slots} slot(s), each swapping {interval}s after "
                          f"its own last connection, independently of the others\n")
        if hasattr(self, "batch_preview_btn"):
            self.batch_preview_btn.configure(text="Stop Batch Preview")

    def _terminal_enabled(self):
        return TERMINAL_SUPPORTED and (self._is_tested("terminal.shell") or self._terminal_unlocked)

    def _term_reader(self, session):
        """Background thread: forwards pty output to the UI queue. Owns the
        master fd and closes it itself, so the UI thread never closes an fd
        this thread might still be reading."""
        fd = session["fd"]
        try:
            while not session["closed"]:
                try:
                    ready, _, _ = select.select([fd], [], [], 0.5)
                except (OSError, ValueError):
                    break
                if not ready:
                    if session["proc"].poll() is not None:
                        break   # shell exited; a leftover background job may hold the pty open
                    continue
                try:
                    data = os.read(fd, 4096)
                except OSError:
                    break   # EIO: the shell and everything on the pty has gone
                if not data:
                    break
                self.log_queue.put(("term_data", session["sid"], data))
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                code = session["proc"].wait(timeout=5)
            except Exception:
                code = None
            self.log_queue.put(("term_exit", session["sid"], code))

    def _term_close_session(self):
        """Safe from atexit/signal handlers: touches no widgets."""
        session = getattr(self, "_term", None)
        if session is None:
            return
        self._term = None
        session["closed"] = True
        end_terminal_session(session["proc"])

    def _cleanup_subprocesses(self):
        """Kill every subprocess this app spawned. Called from the normal
        window-close path AND from a SIGTERM handler / atexit hook (see
        module-level setup below), so cleanup happens regardless of how the
        app's process actually ends -- not just a clean window close. This
        is what stops an orphaned watchdog from surviving the app closing,
        on top of each daemon's own --parent-pid self-check as a second,
        independent layer (in case even this never runs, e.g. SIGKILL).
        Safe to call more than once (e.g. both window-close and atexit
        firing) -- clears its own bookkeeping so a repeat call is a no-op."""
        if getattr(self, "_debug_daemon_enabled", False):
            os.environ["PATH"] = getattr(self, "_debug_original_path", os.environ.get("PATH", ""))
            self._debug_daemon_enabled = False
        for proc in list(self.toggle_procs.values()):
            kill_process_group(proc, force=True)
        self.toggle_procs.clear()
        if self.batch_slot_threads:
            self._stop_batch_cycle_thread()
        for proc in list(self.batch_scrcpy_procs.values()):
            kill_process_group(proc, force=True)
        self.batch_scrcpy_procs.clear()
        for proc in list(self.scrcpy_procs.values()):
            kill_process_group(proc, force=True)
        self.scrcpy_procs.clear()
        if self.current_proc is not None:
            kill_process_group(self.current_proc, force=True)
            self.current_proc = None
        self._term_close_session()

    def _warn_if_other_instance_running(self):
        """Best-effort, non-destructive: if a watchdog-style process from
        another instance of this app (or a genuine leftover from one that
        didn't clean up) is already running, say so. Doesn't kill or touch
        anything -- multiple instances running their own toggles
        independently isn't dangerous, just confusing (e.g. closing one
        window's Stay-Awake while a second instance's is still quietly
        running elsewhere, easy to lose track of). Called before we start
        any of our own watchdogs, so anything found here definitely belongs
        to something else. Linux/macOS only (uses `ps`); silently does
        nothing if that's unavailable -- this is a convenience heads-up,
        not something worth failing startup over."""
        try:
            result = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True, timeout=5)
        except Exception:
            return
        if result.returncode != 0:
            return

        scripts_dir_str = str(self.scripts_dir)
        watchdog_names = ("stayAwake.sh", "heartbeatMaintain.sh", "massConnect.sh", "sync_files.py")
        found = []
        for line in result.stdout.splitlines()[1:]:
            parts = line.strip().split(None, 1)
            if len(parts) != 2:
                continue
            pid_str, cmdline = parts
            if scripts_dir_str not in cmdline:
                continue
            if not any(name in cmdline for name in watchdog_names):
                continue
            found.append((pid_str, cmdline.strip()))

        if found:
            lines = "\n".join(f"  PID {pid}: {cmd[:100]}" for pid, cmd in found)
            messagebox.showwarning(
                "Another instance may be running",
                f"Found {len(found)} background watchdog process(es) already running from the scripts "
                f"folder this app uses, from BEFORE this window started anything of its own:\n\n{lines}\n\n"
                f"This usually means another instance of this app is already open somewhere (or a "
                f"previous one didn't fully close). Nothing has been touched -- just flagging it, since "
                f"closing one window's watchdog while a second instance's is still quietly running "
                f"elsewhere can look like a background process 'wouldn't die' when really it's a "
                f"different instance entirely. Check for other open windows of this app before assuming "
                f"anything is stuck.")


_active_panel = None  # set by main(); read by _handle_termination_signal


def _handle_termination_signal(signum, frame):
    """SIGTERM (a task manager or `kill`), SIGINT (Ctrl+C, or an IDE's Stop
    button) and SIGHUP (the terminal that started it closed): clean up every
    process the panel started, then ask Qt to quit. It never raises -- an
    exception here would surface inside some Qt callback instead of ending the
    program. Python only gets to run this handler while Python code is running,
    which the log pump's 100 ms timer guarantees; each daemon's own --parent-pid
    check covers whatever this can't reach (SIGKILL, a hard crash)."""
    if _active_panel is not None:
        try:
            _active_panel._cleanup_subprocesses()
        except Exception:
            pass
    app = QApplication.instance()
    if app is not None:
        app.quit()


def _report_unhandled(exc_type, exc, tb):
    """An error inside a Qt callback doesn't stop the panel; Python prints it and
    carries on. Double-clicked, there's no terminal to print to, so it also goes
    into the live log, where it can be seen and reported."""
    sys.__excepthook__(exc_type, exc, tb)
    panel = _active_panel
    if panel is not None:
        import traceback
        text = "".join(traceback.format_exception(exc_type, exc, tb)).rstrip()
        panel.log_queue.put(("line", f"\n[panel error -- please report this]\n{text}\n"))


def make_app(argv=None):
    """The QApplication with the panel's look (Fusion style, fonts, style sheet).
    Tests use this too, so they see exactly what the user sees."""
    app = QApplication.instance() or QApplication(list(argv if argv is not None else sys.argv))
    app.setApplicationName("CXVR Control Panel")
    app.setStyle("Fusion")
    app.setFont(app_font())
    app.setStyleSheet(QSS)
    return app


def _save_screenshots(app, panel, out_dir):
    """--screenshot DIR: every ported page as a PNG, then exit. Starts nothing."""
    os.makedirs(out_dir, exist_ok=True)
    width, height = (int(v) for v in os.environ.get("SHOT_SIZE", "1280x860").split("x"))
    panel.resize(width, height)
    panel.show()
    for name, opener in (("connect", panel.show_menu_connect), ("volume", panel.show_menu_volume),
                         ("power", panel.show_menu_power), ("heartbeat", panel.show_menu_heartbeat),
                         ("testing", panel.show_menu_testing)):
        opener()
        for _ in range(6):
            app.processEvents()
        panel.grab().save(os.path.join(out_dir, f"{name}_{width}x{height}.png"))
    panel.close()


def main():
    global _active_panel
    shots = None
    if "--screenshot" in sys.argv:
        index = sys.argv.index("--screenshot")
        shots = sys.argv[index + 1] if index + 1 < len(sys.argv) else "cxvr_screenshots"
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = make_app()
    panel = ControlPanel(safe_preview=shots is not None)
    _active_panel = panel

    for name in ("SIGTERM", "SIGINT", "SIGHUP"):
        if hasattr(signal, name):
            try:
                signal.signal(getattr(signal, name), _handle_termination_signal)
            except (ValueError, OSError):
                pass  # e.g. not running in the main thread -- skip, other layers still apply

    # Final fallback: fires on normal interpreter shutdown, sys.exit(), and
    # most unhandled exceptions (not on SIGKILL/os._exit(), which is exactly
    # why the --parent-pid self-check in each daemon exists as a backstop
    # that doesn't depend on this process getting to clean up at all).
    atexit.register(panel._cleanup_subprocesses)
    sys.excepthook = _report_unhandled

    if shots is not None:
        _save_screenshots(app, panel, shots)
        return 0
    panel.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

# CXVR Fleet Control Panel — instructions for Claude Code

The project instructions from the claude.ai project "VR Video Deployment", adapted for Claude Code.
Read `docs/handoff.md` first, then `docs/HANDOFF_DETAILED.md`. The other docs in `docs/` are the project's
reference documents.

## Context
You're helping maintain the control panel for CulturalXchange.org's mobile VR theater: a fleet of about 70
Oculus Go headsets running the Headjack app `com.CulturalXchange.BibleSchool`, managed over wireless ADB
(172.16.16.0/24, port 5555). The panel is one self-contained Python file that embeds its helper scripts as
strings in `EMBEDDED_SCRIPTS`.

A port from Tkinter to PySide6 (Qt) is in progress. Until cutover there are two panel files:
- `cxvr_control_panel.py`: the Tkinter panel (stdlib only). Frozen: it stays the production tool until the
  Qt panel passes a rehearsal (a simulated show with the whole fleet). Critical fixes only, each mirrored
  into the Qt file and logged in the plan (`docs/cxvr_pyside6_port_plan.md` §13 mirror log).
- `cxvr_control_panel_qt.py`: the PySide6 port (Phase 1 done).

The user's laptop: Cinnamon on X11, with Python 3.11.2 (both the system Python and the venv at
`/home/user/.pyvenv`) and PySide6 6.11.2 in that venv. The user starts the panel by double-clicking the .py
file in Thunar, which runs it with the system Python. So the Qt panel relaunches itself with
`~/.pyvenv/bin/python` when PySide6 is missing.

## Files in this repository
- `cxvr_control_panel.py`: the frozen Tk panel as of 30 Sep 2026: 3,869 lines,
  md5 `fab822033fc7b83cf95b9bbf026ce6c1`. If the user's production copy differs, ask which one is current.
- `cxvr_control_panel_qt.py`: the Qt panel, Phase 1: 4,337 lines, md5 `da5b000262234c5cf7f08d6be8ef7e57`.
- `port_kit/`: port kit v1 (tests; see `port_kit/README.md`).
- `repro/c1_headtracking_stdin/`: reproduction of the critical bug C1 and proof of its fix.
- `docs/`: the hand-off, the state summary, the port plan, the audit and the audit fix plan.

Never reconstruct a file from a summary or from memory. If a file you need isn't here, ask for it.

## Standing rules from the user
1. GUI only. The user operates everything through the panel. Any new CLI flag in an embedded script needs a
   matching GUI control, or it is unreachable.
2. Untested features go under Testing. New or materially changed features that the user hasn't confirmed on
   real headsets must be added to `GATED_FEATURES` and `_testing_items()`, and hidden from their normal
   menu until the user clicks Mark tested.
3. Stronger model when it matters. If a step would benefit greatly from a stronger model (design or planning,
   safety-critical detection logic, large risky refactors), stop before doing it and say which model and which
   effort level to switch to. Rough guide: design and planning → Max; large builds → Extra high; small,
   well-defined fixes → High on the current model.
4. Long conversations. Once a session gets long (30 exchanges, or several large code blocks), suggest
   starting a new session once, and offer to write an extensive hand-off file for the next session.
5. If the task touches a gated feature, ask which features the user has marked tested (stored in their
   config, not in the file). As of 6 Oct 2026 this is still unknown.

## Safety principles for anything that acts on headsets
- Never act on missing information. An unreadable device, a timed-out scan or an unrecognized dumpsys
  format means skip, never "assume the bad state".
- Anything that can act on its own (watchdogs, daemons) ships observe-only and needs an explicit arm step
  with a confirmation that quotes the exact pattern or threshold.
- Automated actions must honor both brakes: `~/.cxvr_control_panel/show_mode` and `sync_in_progress`.
- Destructive or irreversible actions (power off, delete, prune) confirm first and name the exact scope,
  e.g. "headset 172.16.16.28:5555", not "all". Dry run defaults on where one exists.
- Don't guess how Headjack or the Oculus firmware behaves. Build detection from captured evidence (the
  Diagnostic Snapshot tool, real logs), and say plainly when something is unverified.

## Claude Code on a machine that can reach the fleet
This repository may sit on the show laptop, where `adb` reaches real headsets.
- Never run an adb command against a real headset, and never start the panel or an embedded script
  against the real fleet, without the user's explicit OK for that exact command in the current conversation.
  That includes "read-only" calls: they still load the WiFi the films stream over.
- Never run `adb root`, `adb kill-server`, `adb disconnect`, `input keyevent`, `reboot`, `setprop`,
  `settings put`, `svc`, `am`, `push` or `rm` on a headset on your own initiative.
- Tests use the port kit's stubs and fake adb binaries, prepended to `PATH`. Check `which adb` inside a
  test before trusting it.
- Never overwrite the panel file the user double-clicks, or anything in `~/.cxvr_*`, without asking. Work
  in this repository, ideally on a branch, and tell the user which file to copy where.

## Engineering workflow
- Embedded scripts: extract with `ast.literal_eval`, edit and test the standalone copy, re-embed by exact
  `repr()` replacement (assert exactly one match), then verify byte-exact embedded vs standalone and that
  every other embedded script is unchanged. Until cutover, `EMBEDDED_SCRIPTS` must be byte-identical in both
  panel files.
- Panel methods: locate them by AST line range and replace whole methods; use exact-match replacements
  (assert count == 1) for small edits; check afterwards that no method is defined twice. Copied logic must
  stay identical in both panels (after the three substitutions `tk.StringVar(`→`StringVar(`,
  `tk.BooleanVar(`→`BooleanVar(`, `tk.TclError`→`RuntimeError`); `port_kit/t_integrity.py` checks this.
- Target Python 3.11, like the laptop. Test on a 3.11 interpreter: uv's standalone Python 3.11 includes
  Tkinter, and a venv with PySide6-Essentials 6.11.2 mirrors the laptop's. Avoid 3.12-only syntax and APIs,
  such as reusing the same quote character inside an f-string.
- Always run `py_compile` and `pyflakes`, and `bash -n` for shell scripts.
- Test for real, don't just reason.
  - Qt panel: run offscreen (`QT_QPA_PLATFORM=offscreen`) with the port kit's harness, which stubs process
    spawning, `kill_process_group` (always), threads, `adb devices` and the dialog shims; click real widgets.
  - Prove parity with the port kit's differential suite: the same scenarios run on both panels must produce
    identical commands, dialogs and files, apart from the plan's intentional differences.
  - For layout changes, check every page at 800×640, 960×1040 and 1920×1040 for sideways scrolling, and
    look at the screenshots.
  - Run the port kit's launch tests for the double-click relaunch.
  - Tkinter panel: under Xvfb, clicking real buttons with `invoke()`; set the window size after constructing
    `ControlPanel`, because its `__init__` resets it.
  - Test `sync_files.py` with its monkeypatch harness (see the state summary).
  - The whole kit: `port_kit/run_all.sh cxvr_control_panel.py cxvr_control_panel_qt.py` (about 8 minutes;
    every summary line must say pass). Run it before and after a change.
- Keep edits as replayable scripts. Never hand over anything untested. If work is cut short, say exactly
  what's verified and what isn't.
- When a fix lands in the frozen Tk panel, record the new md5 in the port plan's §13 mirror log and add a
  line to the fix plan's status log (§12). The user keeps copies of the docs in the claude.ai project, so
  tell them which docs changed.

## UI conventions (Qt panel)
- Build pages from the shared components: Card, Caption, InfoButton with the `HELP` dict, Collapsible,
  ToggleRow / ToggleSwitch, ModePill, DevicePicker (`TargetRow` / `_device_picker`), TestingBanner.
- Put actions first and settings after them. Put long explanations behind a "?" button, not between controls.
- Any action that can target one headset uses the shared dropdown (with ALL), never a free-text serial box.
- One primary button per page; the danger style only for irreversible actions; destructive confirmations
  default to No.
- Worker threads never touch widgets; they post to the log queue.

## How to communicate
- The user is practical and hands-on. When they report a problem, find the root cause from their logs or
  data before proposing a fix, and explain it in plain terms.
- Be honest about uncertainty and correct your own earlier mistakes directly.
- Keep replies focused: what changed, what was verified and how, and anything the user needs to do or check
  on real hardware.

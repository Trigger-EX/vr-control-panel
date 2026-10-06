# CXVR port kit v1 (Phase 1, 27 Sep 2026)

Tests for the PySide6 port of the CXVR control panel. See `cxvr_pyside6_port_plan.md` in project
knowledge for the plan. Run everything at the start and at the end of every port chat:

    ./run_all.sh path/to/cxvr_control_panel.py path/to/cxvr_control_panel_qt.py [OUT_DIR]

It needs, as in the plan's section 11:
- `PY311`: a Python 3.11 **with** Tkinter and **without** PySide6 (`pip install uv && uv python install 3.11`;
  default `uv python find 3.11`),
- `VENV_PY`: a 3.11 venv with `PySide6-Essentials==6.11.2 pyflakes` (default `~/venv311/bin/python`),
- `xvfb-run`, `fonts-ubuntu`, `libxcb-cursor0` (`apt-get install -y xvfb fonts-ubuntu libxcb-cursor0`),
- `VHOME` for the launch tests (created with uv if missing).

The whole run takes about 8 minutes. The summary at the end must say `pass` on every line.

## What each step proves

| Step | File | Proves |
|---|---|---|
| 01 compile | `run_all.sh` | Both panels compile on 3.11; pyflakes is clean; `bash -n` passes on every embedded shell script |
| 02 integrity | `t_integrity.py` | `EMBEDDED_SCRIPTS` byte-identical; five verbatim blocks identical; the 83 copied `ControlPanel` methods identical to Tk after the three substitutions; every Tk method accounted for (`common/logic_map.py`); no method defined twice |
| 03/04 stream | `t_stream.py` | The 12 terminal-stream checks, on each panel |
| 05 Tk suites | `tk_tests/` | The frozen Tk panel still passes its session-4 suites (12, 42, 33) |
| 06 differential | `record.py`, `compare.py`, `scenarios.py` | 137 scenarios run on both panels through real widgets; commands, dialogs (with answers), kills, config and sentinel files, the log and the panel state must be identical apart from the plan's section 6 |
| 07 Qt behaviour | `t_qt_behavior.py` | 59 Qt-only checks: switches never flip themselves, confirmations default to No, bindings, docks and saved layout, log colours and 20,000-line cap, a 50,000-line burst, a 200-page soak, `--screenshot` mode starting nothing |
| 08 lifecycle | `t_lifecycle.py` | Real processes: close, SIGTERM, SIGINT, SIGHUP, SIGTERM with a dialog open, SystemExit in a callback, SIGKILL |
| 09/10 visual | `t_visual.py` | 10 states at 800×640, 960×1040 and 1920×1040, plus 125 % scaling: no sideways scrolling, nothing cut off in the strip or sidebar. **Look at the screenshots too** |
| 11 rollback | `t_rollback.py` | The Tk panel starts on a config the Qt panel wrote, keeps the Qt keys, and the Qt panel finds its layout again |
| 12 launch | `relaunch_tests.sh` | The 7 double-click relaunch cases, against the Qt panel |

## The differential suite

- `scenarios.py` lists the scenarios. Each step goes through a real widget, found by its label:
  `("open", "volume")`, `("click", "Set Volume")`, `("type", "volume_level_var", "5")`, `("answer", True)`, and
  so on. The docstring there has the full vocabulary.
- `record.py --panel tk|qt` runs them on a fresh panel each, with the shared stubs from `common/panel_stubs.py`.
  Nothing reaches adb or a real process; `kill_process_group` is always stubbed.
- `compare.py` diffs the two recordings. A difference passes only when a rule in `RULES` explains it:
  - **6.1 + 6.8 navigation.** Tk starts on its Main Menu; Qt opens on Connect.
  - **Phase 2: terminal.** Tk opens its terminal when `terminal.shell` is enabled; the Qt terminal comes in Phase 2.

  Remove the terminal rule when Phase 2 ports the terminal.
- `logic_*` scenarios call the actions whose pages arrive in Phase 2 (sync, the watchdogs, delete video,
  the snapshot) directly on both panels. This proves the copied logic behaves the same through the Qt
  compatibility layer before its page exists. In Phase 2, rewrite them to click the real pages.
- Negative controls were run in Phase 1. Planting a changed log line and a miswired button in the Qt panel
  made compare fail. Changing one word in a copied method, or one character in an embedded script, made
  the integrity test fail.

## Known issues shared by both panels (not caused by the port)

Found by these tests on 27 Sep 2026. Both panels behave identically, and the tests pin that behaviour
until a mirrored fix is approved:
1. **A watchdog that dies within about 0.1 s of starting keeps showing as Running.** Scenario
   `heartbeat_dies_within_one_tick`. `_refresh_toggle_state` compares against a snapshot that
   `_start_toggle` never updates.
2. **`timeout`-wrapped adb calls outlive the panel by up to about 20 s.** Seen in `t_lifecycle.py`.
   Coreutils `timeout` moves itself into its own process group, so `kill_process_group` (a killpg) doesn't
   reach it. It stays in the script's session and ends on its own when its timeout runs out.

## Other folders

- `build_phase1/`: how Phase 1 assembled the Qt file (`assemble.py` plus the Qt-only `parts/`). It reproduces
  the shipped file byte for byte from the frozen Tk panel. From Phase 2 on, edit the Qt file itself.
- `tk_tests/`: the session-4 Tk tests (`harness.py`, `t_term.py` and the rest). `t_pkg.py`, `t_cell.py`,
  `run_sweep.sh`, `t_fine.py` and `t_loop.py` are kept for reference.
- `design_reference/`: the approved look-only preview and its screenshots.
- `experiments/qt_signal_experiment.py`: why the 100 ms log-pump timer must keep running (signals).
- `fakebin_lifecycle/adb`: a fake adb that reports one headset and hangs when asked to talk to it.
- `screenshots/`: the Phase 1 review set.

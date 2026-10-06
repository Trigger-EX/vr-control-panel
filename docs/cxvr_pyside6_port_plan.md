# CXVR Control Panel — PySide6 Port Plan

Plan v1.3 · 30 Sep 2026 (v1.2: 27 Sep) · written at Max effort; Phase 0 and Phase 1 results added on 27 Sep;
the audit and its fix plan added on 30 Sep. The status log (§13) is updated once per phase.
Companion doc: `cxvr_project_state_summary_v4.md` (what the panel does today).

---

## 1. The plan in brief

- **What:** rebuild the panel's user interface in PySide6 (Qt), and keep everything that talks to headsets
  exactly as it is. About 1,950 lines of logic (actions, command builders, process handling, the scrcpy
  engine, the terminal backend) and all 15 embedded scripts move across unchanged. About 1,090 lines of
  Tkinter UI get rewritten in the sidebar-and-cards design from the preview.
- **How we know it's right:** a differential test suite runs the same scenarios against the current
  Tkinter panel and the new Qt panel. Both must produce identical commands, confirmations and file
  changes, apart from a short, written list of intentional differences (§6).
- **Safety net:** the Tkinter panel is frozen and stays the production tool until the Qt panel has passed
  a rehearsal with real headsets. Both use the same config file, so going back means starting the old
  file. Nothing else needs undoing.
- **Shape:** five build phases, one chat each (the first two may need two). Each phase ends with a
  working, tested file: Foundation → Remaining pages → Screen Capture parity and hardening → New Screen
  Capture features (grid, Prev/Next, double view) → Rehearsal and cutover. Five to seven chats in total.
- **Next:** the four audit-fix batches in `cxvr_audit_fix_plan.md` (Batch 1 first, Opus 5.5 at Extra high),
  then Phase 2, so Phase 2 ports the fixed logic. Phases 0 and 1 are done (§3, §3b).

## 2. Goals, non-goals and what "done" means

**Goals**
1. Every feature of the current panel works in Qt, reached through the GUI, with identical effects on
   headsets.
2. The new layout: sidebar navigation, Show Mode always visible, the log and terminal in dockable panes,
   cards and switches, as in the preview.
3. Drop the Tkinter layout workarounds (canvas-in-scroll-area, caption re-wrapping, scrollbar reservation)
   that caused the two freezes fixed in September.
4. Then add the approved Screen Capture features.

**Non-goals during the port**
- No changes to embedded scripts, adb commands, safety behaviour or detection logic. **Exception (30 Sep
  2026, at your request):** the audit-fix batches in `cxvr_audit_fix_plan.md` make exactly these changes,
  in both panel files, before Phase 2. The port phases themselves keep this rule.
- No new features except the approved Screen Capture ones (Phase 4). New ideas go to the parking lot (§12).
- No splitting into multiple files. That can be revisited after cutover.

**Done means**
1. Differential suite: every scenario identical, or covered by §6.
2. Lifecycle: no leftover processes after closing the window, SIGTERM, SIGINT or a crash, tested with
   real processes. (One pre-existing exception shared with the Tk panel is recorded in §14.)
3. Layout: every page usable without sideways scrolling at 800×640, 960×1040 and 1920×1040, with the
   screenshots reviewed.
4. Responsiveness: a 50,000-line log burst doesn't freeze the window.
5. Rollback proven: the Tkinter panel starts cleanly on a config written by the Qt panel.
6. You've run the acceptance checklist (§9) with real headsets, then used the Qt panel for one real show.

## 3. Phase 0 — results (27 Sep 2026)

**The laptop**
- Python 3.11.2 (the system Python and the venv at `/home/user/.pyvenv`), PySide6 6.11.2 in the venv,
  Cinnamon on X11, and Thunar as the file manager.
- The preview runs and looks right. The one message it printed,
  `qt.accessibility.atspi: … "GetApplicationBusAddress"`, comes from Qt's accessibility bridge and is
  harmless.
- The user starts the panel by double-clicking the .py file in Thunar. Thunar starts it with the system
  Python, which has no PySide6, so the Qt panel relaunches itself with the venv Python (§4.9). This is proven
  in the preview (7 launch cases, plus the error window). Still waiting on the user's double-click of the
  updated preview on the laptop.
- The current Tkinter panel passes its test suites on Python 3.11 (12/12, 42/42, 33/33), so this chat's
  changes are safe on the laptop's Python.

**Schedule:** no show soon. The rehearsal will be a simulated show with the whole fleet, whenever the user
sets one up.

**Decisions:** the defaults were assumed; the user can change any of them at the start of Phase 1.
- D1 File: one file, `cxvr_control_panel_qt.py`, renamed to `cxvr_control_panel.py` at cutover.
- D2 Code between chats: the user uploads the frozen Tkinter panel, the latest port kit and, from Phase 2
  on, the Qt panel.
- D3 Order: the new Screen Capture features (Phase 4) come before the rehearsal.
- D4 Window: during shows the panel sits on the left half of the laptop (about 960×1040); otherwise it's
  maximized.
- D5 Launch page: Connect.

**Project instructions:** the updated text is Appendix A. The user pastes it into the project settings;
Claude can write project docs but not the instructions.

## 3b. Phase 1 — results (27 Sep 2026)

**Built:** `cxvr_control_panel_qt.py` (4,337 lines, 414 KB), assembled by `build_phase1/assemble.py` in
the kit from the frozen Tk panel (md5 `fab82203…`, 3,869 lines) plus the Qt-only parts. The assembler
reproduces the file byte for byte. From Phase 2 on, edit the Qt file itself.
- Copied verbatim and checked by `t_integrity.py`: the 15 embedded scripts; five module blocks (constants,
  embedded scripts, process helpers, terminal backend, palette + `HELP`); 83 `ControlPanel` methods, after
  the three substitutions `tk.StringVar`→`StringVar`, `tk.BooleanVar`→`BooleanVar`,
  `tk.TclError`→`RuntimeError`. Every one of the Tk panel's 153 methods is classified in
  `common/logic_map.py`: 83 copied, 34 rewritten, 2 dropped (the main menu), 34 later (Phase 2/3 pages and
  the terminal UI).
- The window: a one-row strip (two rows below 1,200 px wide) with chips for background tasks, the Show Mode
  switch, and the three always-available buttons. The sidebar is a locked left dock with a "later" tag on
  pages not ported yet, a Testing badge and Live log / Terminal pane toggles. The page area scrolls. The
  Live log and Terminal docks are tabbed; the layout is saved in `window_geometry` / `dock_state`, and a
  pane floated onto a monitor that's gone is brought back.
- Pages: Connect, Heartbeat, Volume, Power, the Testing hub and Testing › Power. The other pages are
  placeholders that name the phase that brings them. The Terminal pane shows when `terminal.shell` is
  enabled, but its contents arrive in Phase 2.
- The log pump is a 100 ms QTimer, capped at 2,000 lines per tick. The on-screen log keeps 20,000 lines.
- Lifecycle: close, SIGTERM, SIGINT and SIGHUP run cleanup and then quit; the atexit hook runs too; an
  unexpected error in a Qt callback is also written to the live log.
- `--screenshot DIR` renders the main pages to PNGs and exits without starting anything. It's used by the
  launch tests, and you can use it to send screenshots from the laptop.

**Verified (port kit v1, all passing from a clean unzip):** integrity 58/58; terminal stream 12/12 on both
panels; the Tk suites 12/42/33; differential 137 scenarios, 81 identical and 56 differing only as §6
allows; Qt behaviour 59/59; lifecycle 7/7 with real processes; visual 180/180 at the three sizes plus
120/120 at 125 % scaling, with the screenshots reviewed; rollback 8/8; launch 7/7. The negative controls
failed as they should: planted bugs were caught by the comparer and by the integrity test. The panel also
ran on a real X server (xcb under Xvfb): it started, drew, ran a Headtracking cycle against a fake adb,
and exited cleanly on SIGTERM.

**Not verified yet:**
- The laptop itself: fonts, Cinnamon's window manager, a double-click in Thunar and a real second
  monitor for a floated pane.
- Anything with real headsets.

## 4. Architecture of the Qt panel

### 4.1 One file, clear layers
Sections, in order:
1. Standard-library imports, then the double-click relaunch (§4.9), then the PySide6 imports.
2. Constants and config, copied verbatim (`APP_PACKAGE`, the subnet and scrcpy constants,
   `GATED_FEATURES`, `HELP`, the palette).
3. `EMBEDDED_SCRIPTS`, byte-identical to the Tkinter file until cutover (enforced by a test).
4. Process and platform helpers, copied verbatim: `materialize_scripts`, `popen_in_own_group`,
   `kill_process_group`, `compute_tile_layout`, `load_config`/`save_config`, and the terminal backend
   (`TerminalStream`, `spawn_terminal_session`, `end_terminal_session`).
5. Compatibility layer (new, small): `Var`, dialog shims, `ToggleSwitch` (§4.3).
6. Design system: the QSS stylesheet and shared components (§4.6).
7. `ControlPanel`: the Qt window and page builders first, then a marked line, then the logic methods
   copied verbatim apart from mechanical substitutions, in the Tk file's order.
8. `main()`: the QApplication, signal handlers and atexit hook.

### 4.2 What's copied and what's rewritten
Measured on the current file (3,869 lines, 409 KB):

| Part | Size | Treatment |
|---|---|---|
| Embedded scripts (15) | 196 KB, 48% of the file | copied byte-for-byte |
| Module-level helpers and terminal backend | 12 functions, 2 classes | copied |
| Logic inside `ControlPanel`: settings, gating, run/stop/interrupt, command builders, 33 actions, scrcpy engine, terminal sessions | about 1,950 lines, about 140 Tk touchpoints | copied; the Tk touchpoints go through the compatibility layer |
| UI: styles, window chrome, components, 15 page builders | about 1,090 lines, about 440 Tk touchpoints | rewritten in Qt |

### 4.3 Compatibility layer: why the logic can be copied unchanged
The logic uses Tk in these ways only. Each gets a Qt stand-in with the same API, so the logic methods keep
their exact text:
- **Settings variables.** There are 53 (35 text, 18 on/off). `Var` provides `.get()`, `.set()` and change
  callbacks. It's plain Python, so worker threads can safely read it; three settings are read from scrcpy
  threads today. Widgets bind to Vars in both directions, and a binding is dropped when its widget is
  deleted (a 200-page soak shows no build-up). Values stay strings wherever Tk used a StringVar, because the
  logic validates strings (`.strip()`, `.isdigit()`). `BooleanVar` reads strings the way Tcl does.
- **Dialogs.** Module-level `messagebox` and `filedialog` objects with the Tk function names (`showerror`,
  `showwarning`, `showinfo`, `askyesno`, `askdirectory`, `askopenfilename`), implemented with QMessageBox
  and QFileDialog. The 38 message calls, 12 confirmations and 3 file pickers keep their exact wording,
  shown as plain text. **All** confirmations default to No (§6).
- **Start/Stop toggles.** `ToggleSwitch` is a switch that also accepts `configure(text="Start…")` or
  `configure(text="Stop…")` and `cget("text")`, the way the Tk `ToggleButton` does; there are 9 relabel
  call sites. It never flips itself when clicked. Only the action sets its state, so a refused start
  (invalid interval, arm confirmation declined) leaves it off.
- **A few widget calls** found while porting: `Button.configure(state=)` (disabling one-shot buttons while
  a script runs), `Combo.configure(values=)` (after a Refresh), and `configure(foreground=)` on the
  failed-count label.
- **Timers.** `root.after` appears 8 times, all in UI code that's being rewritten anyway. The log pump
  becomes a QTimer.

This also means the existing test stubs (`messagebox.*`, `popen_in_own_group`, `kill_process_group`,
`threading.Thread`, `subprocess.run`) work unchanged on the Qt panel.

### 4.4 Threads, the log queue and signals
- The threading model stays exactly as it is. Seven kinds of worker thread (one-shot run, toggles, scrcpy
  launch and ready-wait, Capture All, batch slots, the terminal reader) never touch widgets. They put
  messages on `log_queue`, which carries seven message kinds. An audit of the current code found every
  worker already follows this rule.
- A 100 ms QTimer drains the queue with the same handlers as `_poll_log_queue` and refreshes the toggle
  state and terminal echo mask. Work per tick is capped (2,000 items) so a sync flood can't freeze the
  window. Measured: a 50,000-line burst drained in about 2.4 s, with the worst tick at 42 ms.
- **The same timer is also what lets shutdown signals through.** Tested while writing this plan: while Qt's event
  loop is idle, Python signal handlers don't run at all. A SIGTERM was ignored and the panel's child
  process was orphaned. With a 100 ms timer running, the handler ran and cleanup worked. So the SIGTERM
  and SIGINT handlers must run cleanup and then call `QApplication.quit()`, never raise. A lifecycle test
  guards this, in case the timer is ever removed or slowed down.
- In test mode (`CXVR_ASSERT_MAIN_THREAD=1`), UI updates assert they're running on the main thread. Where
  Tkinter merely misbehaves, Qt crashes.

### 4.5 Window structure
- **Top strip:** the four status numbers, background tasks shown as chips, the **Show Mode switch** (it
  turns the strip amber and shows a banner), and the Stop all tasks, Interrupt script (always enabled) and
  Kill ADB server buttons.
- **Sidebar:** Fleet (Connect, Sleep / Wake, Volume, Power, Heartbeat), Content (Content Sync, plus Delete
  Video once tested), View & debug (Screen Capture, Debug Tools), and Testing, with a badge counting
  untested features.
- **Page area:** a scroll area. Each page is rebuilt when it's opened, as now, so gating changes show
  immediately, and the old page's widgets are deleted.
- **Live log and Terminal:** two dock panes, tabbed at the bottom by default. They can be placed side by
  side or floated onto the second monitor, and the arrangement is saved in the config. Each dock needs an
  object name, or Qt can't save the arrangement. The Terminal pane only exists when `terminal.shell` is
  tested, or unlocked for the session from Testing.
- **Layout targets:** 960×1040 (the main one during shows, if D4 holds), 1920×1040 maximized, and a
  minimum of 800×640. Below about 1,100 px wide, Screen Capture stacks its Live view card under the grid.

### 4.6 Design system: Tk component to Qt component

| Tk | Qt |
|---|---|
| `_card(title, right=)` | `Card`: frame with a header strip, optional right-side widgets and a "?" |
| `_caption` and its re-wrap workaround | `Caption`: a word-wrapped QLabel; Qt re-wraps natively |
| `_info_button` with `HELP` | `info_button`: the same `HELP` text in a message box |
| `_collapsible` | `Collapsible`: header and body; open state remembered for the session |
| `_toggle_row` with `ToggleButton` | `ToggleRow`: dot, name, Running pill, caption, inline settings, "?", `ToggleSwitch` |
| `_mode_pill` | `ModePill`: Observe only / Armed, following its variable |
| `_target_row` / `_device_picker` | `TargetRow` / `_device_picker`: read-only `Combo` with an ALL entry, plus Refresh |
| `_testing_banner`, `_mark_tested_right`, `_back_to_testing` | `TestingBanner`, `_mark_tested_button`, a "‹ Testing" link |
| Primary / Danger / Small / Nav styles | QSS object names `primary`, `danger`, `big`, `small`, `link` |

The stylesheet uses the existing palette, on top of Qt's Fusion style so it looks the same on any
desktop. The existing rules still apply: one primary button per page, the danger style only for
irreversible actions, actions first and settings after, and long explanations behind "?". The preview
app (in port kit v0.1) is the visual reference.

### 4.7 Lifecycle
- Closing the window saves the window and dock layout, then runs `_cleanup_subprocesses`, the same
  function as today.
- SIGTERM, SIGINT and SIGHUP run cleanup, then quit.
- The atexit hook runs cleanup again; it's safe to run twice.
- The other-instance warning and the headtracking watchdog auto-start stay unchanged.
- At startup, the log records the Python, PySide6 and Qt versions and the platform (xcb on the laptop).
- If PySide6 can't be imported, the double-click relaunch (§4.9) takes over.

### 4.8 Config, files and running side by side
- Same `~/.cxvr_control_panel/config.json` with the same keys. New keys are only ever added
  (`window_geometry`, `dock_state`), never removed. The Tkinter panel keeps and ignores keys it doesn't
  know, so rollback works; `t_rollback.py` proves it.
- The same sentinel files (`show_mode`, `sync_in_progress`); the same log, snapshot and probe folders; and
  the same embedded-scripts folder, whose contents are identical by rule.
- Don't run both panels at once. The other-instance warning flags the other panel's watchdogs.

### 4.9 Environment and launching
- The laptop runs Python 3.11.2, with PySide6 6.11.2 in `/home/user/.pyvenv`, on Cinnamon (X11). **All code
  must run on Python 3.11.** That means no 3.12-only syntax (for example, reusing the same quote character
  inside an f-string) and no 3.12-only APIs. Tests run on Python 3.11 (§11).
- **Double-click launch.** The user double-clicks the .py file in Thunar, which starts it with the system
  Python.
  - Before importing PySide6, the file checks whether it can. If it can't, it starts itself again with
    `~/.pyvenv/bin/python` (or `$CXVR_QT_PYTHON`), at most once (the `CXVR_RELAUNCHED` flag).
  - If no suitable Python is found, it prints the reason and also shows it in a Tk error window, because a
    double-clicked program has no terminal.
  - A venv's `python` is a symlink to the system Python, so candidates are compared by their path, never by
    the binary they resolve to.
  - Proven in the preview with the kit's `relaunch_tests.sh`, 7 cases: open-with, executable file via its
    first line, relative path, no venv, same Python, direct venv and the loop guard. The error window was
    also checked. Phase 1: the same 7 cases pass against the Qt panel.
- After the relaunch, `sys.executable` is the venv's Python, and the embedded Python scripts are started with
  it. They're stdlib-only, so that's fine.
- A .desktop menu entry is optional (Phase 3). On X11, Qt 6.5 and later needs `libxcb-cursor0`; the preview
  runs on the laptop, so it's present.

## 5. Page-by-page mapping

| Tk menu | Qt | Notes |
|---|---|---|
| Main Menu | removed | Its buttons move to the sidebar; Show Mode moves to the top strip |
| Connect / Reconnect | Connect | Normal Connect (primary), Full Scan, Purge & Reconnect; visual-check option. **Ported in Phase 1** |
| Sleep / Wake | Sleep / Wake | Target; Wake / Sleep / Screen refresh; watchdogs: Stay Awake, Keepalive, Headtracking (+ Verbose), Popup recovery (+ interval). Overheat and Black-screen rows appear only when tested; their arm confirmations still quote the pattern and threshold |
| Volume Control | Volume | Target; last-operation note; Check; presets; exact level. **Ported in Phase 1** |
| Power Management | Power | Target; Reboot, and Power Off (danger style), when tested. **Ported in Phase 1** |
| Heartbeat | Heartbeat | One toggle row. **Ported in Phase 1** |
| Content Sync | Content Sync | Run (Sync is primary; Verify; Dry Run); Source & destination with Save; Options; Advanced (collapsible, includes the bandwidth diagnostic). All guards and the prune confirmation unchanged |
| Delete Video | Delete Video | Sidebar item once tested; dry run on by default |
| Debug Tools | Debug Tools | ADB traffic log; Diagnostic Snapshot when tested |
| Screen Capture | Screen Capture | Phase 3: the same controls as today. Phase 4: grid, Live view card, double view |
| Testing and its sub-pages | Testing | Hub, plus the Power, Sleep / Wake, Snapshot and Terminal pages. **Hub and Power ported in Phase 1** |
| Live log and Terminal panes | Dock panes | See §4.5 |

## 6. Intentional differences (the only ones allowed)
Each of these is in the differential suite's allow-list, or is something the suite doesn't record (a
default button, a widget's look). Any other difference is a bug.
1. Navigation: a sidebar instead of the Main Menu and Back button; Testing sub-pages have a "‹ Testing"
   link. Notices say "open Testing in the sidebar" instead of "Main Menu › Testing".
2. Show Mode is a switch in the top strip, with an amber banner while it's on. Same file, same effect.
3. Start/Stop buttons become switches with a Running pill.
4. The log and terminal are dock panes. The saved dock layout replaces `log_hidden` and
   `terminal_hidden`, which are left in the config, unused.
5. **All** confirmations default to No (Tkinter defaulted to Yes). Phase 1 extended this from destructive
   actions to all 12, since every one of them guards something that acts on headsets.
6. The on-screen log keeps the last 20,000 lines. Full logs are still written to files.
7. Once tested, Delete Video appears in the sidebar rather than on a main menu, and the banner wording
   says "the sidebar".
8. The panel opens on Connect (D5).
9. Phase 4 only: the Screen Capture headset grid, Prev/Next and double view, gated under Testing.
10. The mouse wheel never changes a dropdown. In the Tk panel, a wheel notch over a read-only headset picker
    changes the target (verified); in Qt, the page scrolls instead. The volume level field steps with − / +
    or the arrow keys, and ignores the wheel unless it has focus.
11. Background-task chips show friendly names ("Headtracking" for `htWatchdog`); the underlying text is the same.
12. SIGHUP cleans up too, and SIGINT (Ctrl+C) cleans up rather than raising KeyboardInterrupt.
13. An unexpected error inside a Qt callback is also written to the live log (there's no terminal when
    double-clicked).
14. Until each page is ported, its sidebar item is tagged "later" and opens a placeholder page. The window
    title says "(Qt)" until cutover.

## 7. Testing strategy: the port kit
A zip ships with every phase (`cxvr_port_kit_vN.zip`). All of it runs at the start and at the end of
every chat: `./run_all.sh TK_PANEL QT_PANEL` (about 8 minutes; every line of its summary must say pass).
- **Harnesses:** `harness_tk.py` (Xvfb, with today's stubs) and `harness_qt.py` (offscreen Qt, with the same
  stubs plus the Qt dialog shims), behind one adapter API. The shared stubs are in `common/panel_stubs.py`.
- **Differential suite:**
  - `scenarios.py` lists scenarios declaratively: the page, the settings to set, the button to click (by
    label, so the wiring is tested too) and the answers to any confirmations.
  - `record.py --panel tk|qt` runs them and writes JSON: spawned command lines (with script paths
    normalized) and the sentinel files at the moment of spawning, processes signalled, dialogs (kind,
    title, text, answer), `subprocess.run` calls, changes to the config and sentinel files, the text added
    to the log, and the panel's state.
  - `compare.py` diffs the two recordings against the §6 allow-list.
  - Phase 1: 137 scenarios. 107 go through the Phase 1 pages and the top strip: confirm and cancel paths,
    validation errors, ALL vs one headset, gating states (none tested, all tested, each alone) and runs
    held open to test Interrupt. Another 30 `logic_*` scenarios call the actions whose pages arrive in
    Phase 2 directly on both panels. In Phase 2 they become click-through scenarios.
- **Integrity:** `t_integrity.py` checks `EMBEDDED_SCRIPTS`, the verbatim blocks and every copied method
  against the Tk file, using `common/logic_map.py`. `run_all.sh` adds `py_compile`, `pyflakes` and
  `bash -n`, including `bash -n` on every embedded shell script.
- **Qt behaviour tests:** `t_qt_behavior.py` (59 checks). The Tk click-through (33) and terminal (42)
  suites still run on the Tk panel. The terminal suite gets its Qt port in Phase 2; the stream suite (12)
  already runs on both panels.
- **Lifecycle tests with real processes:** `t_lifecycle.py` covers close, SIGTERM, SIGINT, SIGHUP,
  SIGTERM with a dialog open, SystemExit in a callback, and SIGKILL (where the daemons' parent check must
  end them). The terminal background-job case comes in Phase 2.
- **Visual:** `t_visual.py`, every page at 800×640, 960×1040 and 1920×1040, plus once at 125% scaling.
  Screenshots are saved; checks assert no horizontal scrolling, nothing cut off in the strip or sidebar.
- **Performance and soak:** a 50,000-line burst and a 200-page soak (both in `t_qt_behavior.py`); the
  two-hour fake-watchdog memory run comes in Phase 3.
- **Python 3.11:** Qt tests run on Python 3.11 with PySide6-Essentials 6.11.2 in a venv, mirroring the
  laptop. Tkinter tests also run on 3.11; uv's standalone Python 3.11 includes Tkinter.
- **Launch tests:** the kit's `relaunch_tests.sh` (7 cases), run against the Qt panel file.
- **Rollback:** `t_rollback.py`.
- **Kit v0.1** (delivered with Phase 0) contains the current Tkinter test scripts, the preview app with the
  relaunch, and the launch tests. Kit v1 includes all of it.

## 8. Phases
Each phase ends with a runnable Qt file, an updated port kit, screenshots, a report of what's verified and
what isn't, and one update to §13.

### Phase 1 — Foundation · Opus 5.5, Extra high (one or two chats) — **done, see §3b**
**Build:**
- A new file, assembled from the Tkinter file's copied sections (§4.1–4.2).
- The compatibility layer.
- The window: strip, sidebar, page area, both docks, and saving the dock layout.
- The log pump.
- Lifecycle: close, SIGTERM, SIGINT, atexit, the other-instance warning and the headtracking auto-start.
- The double-click relaunch (§4.9), copied from the preview, and its launch tests.
- The design-system components and QSS.
- Pages: Connect, Heartbeat, Volume, Power, the Testing hub, and Testing › Power.
- Port kit v1: harnesses, the scenario runner, recorder and comparer, lifecycle tests and visual tests.

**Exit:** the differential scenarios for these pages are identical, the lifecycle and launch tests pass,
screenshots at all three sizes have been reviewed, and the integrity checks pass.
**You:** double-click it on the laptop (no headsets needed), click around, and say what looks or feels off.

### Phase 2 — Remaining standard pages · Extra high (one or two chats)
**Build:**
- Sleep / Wake: all six watchdog rows and the arm flows.
- Content Sync: every field, the guards, the prune confirmation, Advanced and the bandwidth diagnostic.
- Delete Video.
- Debug Tools: the ADB traffic log and the snapshot.
- Testing › Sleep / Wake, Snapshot and Terminal.
- The Terminal dock, at parity with today's terminal. Then remove the comparer's "phase 2: terminal" rule
  and add the terminal lifecycle case.
- Move the `LATER` phase-2 entries in `common/logic_map.py` to `COPIED` or `REWRITTEN`.
- Turn the `logic_*` scenarios into click-through scenarios on the new pages.

**Exit:** the full differential matrix, the gating matrix, and the ported behaviour and terminal suites all
pass; screenshots reviewed.

### Phase 3 — Screen Capture parity and hardening · Extra high
**Build:**
- Screen Capture as it is today: Connect, Capture All (up to 4), Close All, batch preview, window options
  and taskbar grouping.
- Performance, soak, navigation and thread-safety tests, and a final visual pass.
- An optional .desktop menu entry. Double-clicking the file already works.

**Exit:** all suites pass, and you run a short hardware smoke test: connect, a volume check, one screen
capture, one watchdog switched on and off, and closing the panel, after which nothing is left running.

### Phase 4 — New Screen Capture features · Extra high (gated under Testing)
**Build:**
- The headset grid. It reflows with the window width and has a filter and attention colours.
- Prev/Next, the arrow keys and the mouse wheel. Stepping replaces the open view in place, and
  double-click opens a view.
- The Live view card.
- Double view:
  - Detect the virtual camera by its name (`/sys/class/video4linux/*/name`), with setup help that gives
    the exact commands, which can be run in the panel's own terminal.
  - Run scrcpy with `--v4l2-sink`, plus a view-only ffplay window on the chosen monitor. Monitors come from
    `xrandr --listmonitors`, re-read every time a view opens.
  - Both windows close together.
- New gate keys: `screencap.stepper` and `screencap.double_view`.

**Needed from you:** install the virtual camera (`sudo apt install v4l2loopback-dkms`), and paste the
output of `xrandr --listmonitors` with the second monitor connected.
**Exit:** parser and command tests, behaviour tests with fake processes, and screenshots. The
hardware check happens at the rehearsal.

### Phase 5 — Rehearsal, cutover and cleanup · High
You run the acceptance checklist (§9) with the fleet, and Claude fixes what it finds. Then cutover:
- The Qt file becomes `cxvr_control_panel.py`, and the Tkinter file becomes
  `cxvr_control_panel_tk_legacy.py`.
- The launcher and the project instructions are updated.

The legacy file is kept for one show, then retired.

## 9. Acceptance checklist (the rehearsal) and rollback
Run during a simulated show with the whole fleet, with the Qt panel on the show laptop:
1. Double-click the file in Thunar; the panel opens, with all the settings from the Tkinter panel.
2. Connect (normal); the status numbers update.
3. Sleep, then Wake, one headset; then all of them.
4. Volume: check one headset; apply a preset to one headset.
5. Watchdogs: start and stop Stay Awake and Popup recovery. Turn Show Mode on and confirm in the log that
   the overheat watchdog and the black-screen probe (if running) keep logging but send nothing. **Show Mode
   only brakes those two:** Stay-Awake, Keepalive, Headtracking and Popup recovery don't read it and keep
   acting (checked in the embedded scripts, 27 Sep 2026). Turn it off again.
6. Content Sync: a Dry Run, then a real sync to one headset (Advanced › devices).
7. Delete Video dry run on one headset (if marked tested).
8. Diagnostic Snapshot on one headset (if marked tested).
9. Screen Capture: one headset; Capture All; batch preview for a few cycles; Prev/Next through 10
   headsets; double view on the second monitor.
10. Terminal: a local command; a headset shell; Ctrl+C on `logcat`; `exit`.
11. Close the panel, wait 30 seconds, then run
    `ps -eo pid,args | grep -E "scrcpy|ffplay|embedded_scripts|adb -s" | grep -v grep`.
    Nothing started by the panel may be left. The wait is for §14 item 2, unless that fix has been made.
12. Start the Tkinter panel once to confirm that rollback still works, then close it.

**Rollback at any point:** close the Qt panel and start the Tkinter panel as before. Nothing else to undo.

## 10. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| A command changes subtly in the port | Wrong action on headsets | Logic copied verbatim and checked by `t_integrity.py`; differential suite covers every Phase 1 action, and the `logic_*` scenarios cover the rest |
| A worker thread touches a widget | Qt crashes mid-show | Queue-only rule (current code audited clean); main-thread assertions in tests; soak test |
| SIGTERM or Ctrl+C ignored under Qt | Orphaned watchdogs | 100 ms pump plus handlers that quit; lifecycle tests with real processes |
| Confirmation wording drifts | Unclear scope on destructive actions | Dialog text compared by the differential suite |
| The Tkinter panel needs a fix mid-port | The two versions drift apart | Tkinter frozen; critical fixes mirrored and logged; the integrity test fails unless both files change the same way |
| The laptop environment (xcb-cursor, fonts, scaling, venv) | Panel won't start, or looks wrong | Phase 0 checks done; version pinning; versions logged at startup; double-click relaunch with a clear error window |
| The workspace tests on Python 3.12 but the laptop runs 3.11 | Syntax or API errors that only show up on the laptop | Test on a 3.11 interpreter (uv's standalone build, with Tkinter) and PySide6 6.11.2 |
| Both panels running at once | Duplicate watchdogs, confusing state | Other-instance warning; checklist; placeholder pages say to close the Qt panel first |
| A show arrives before the port is done | Pressure to switch early | Tkinter stays production until acceptance |
| A log flood freezes the UI | Panel unusable during a sync | Per-tick cap; line cap; performance test |
| Layout breaks at the real window size | Cramped controls | D4 targets; screenshots at three sizes; your look in Phase 1 |
| Double view misbehaves when stepping (virtual camera + ffplay) | Black or frozen second view | Restart both on every step; unverified until the rehearsal |
| The cloud workspace resets mid-chat (happened in this project) | Lost work | Edits kept as replayable scripts; working files delivered early; port kit re-runnable |
| The frozen logic has bugs of its own (found in Phase 1, §14) | The Qt panel inherits them | Tests pin today's behaviour on both panels; fixes need your approval and are mirrored |

## 11. How each port chat runs (for Claude)
1. Read this plan and `cxvr_project_state_summary_v4.md`. Ask for any missing uploads: the Qt panel (from
   Phase 2 on), the frozen Tkinter panel and the latest port kit. Check the Tk panel is the frozen one:
   3,869 lines, md5 `fab822033fc7b83cf95b9bbf026ce6c1`, unless §13's mirror log records a change.
2. Set up the workspace:
   - `apt-get install -y xvfb fonts-ubuntu libxcb-cursor0 imagemagick`
   - `pip install uv`, then `uv python install 3.11`. Its standalone build includes Tkinter.
   - Make a venv like the laptop's: `uv venv <dir> --python 3.11`, then
     `uv pip install --python <dir>/bin/python PySide6-Essentials==6.11.2 pyflakes`.
   - Run the Tkinter tests with the 3.11 interpreter under Xvfb, and the Qt tests with the venv. Also run
     `py_compile` on everything with 3.11.
3. Run the whole port kit first (`run_all.sh`). It must pass before anything changes.
4. Port page by page: build, run the differential scenarios, run the behaviour tests, take screenshots.
   Keep edits as scripts so they can be replayed if the workspace resets.
5. Never edit the Tkinter file, except for a critical fix the user has approved; mirror that fix into the
   Qt file and log it in §13.
6. At the end: run everything; ship the Qt file and the port kit zip to `/mnt/user-data/outputs/`; report
   what's verified and what isn't; update §13 once with `project_write`.
7. If a step needs more than the phase's effort level (an architecture change, say), stop and say so.

## 12. Parking lot (not during the port)
- Split the file into modules; a dark theme; an overview page.
- Spin boxes or validators for numeric fields (the logic currently validates text).
- ~~Write embedded scripts via a temporary file and rename~~: now in the audit fix plan (B1.12).
- ~~The brief moment in `_run_command` when Interrupt reports "nothing running"~~: now in the audit fix
  plan (B1.2).
- Headset friendly names (a serial → label mapping); grouping headsets by WiFi band in the bandwidth
  diagnostic.
- Field-data work continues separately from the port: the overheat signature, the black-screen threshold
  (a Max-effort task), and the taskbar-grouping check.
- Page content spans the full window width at 1920 px (as in Tk); a maximum content width could look
  tidier.

## 13. Status log

| Date | Phase | Result |
|---|---|---|
| 27 Sep 2026 | Plan | Written. Port kit v0 delivered. |
| 27 Sep 2026 | Phase 0 | Results in §3. Double-click relaunch proven in the preview; waiting on the user's double-click check. Defaults assumed for D1–D5. Port kit v0.1 (updated preview, launch tests, 3.11 notes). Next: Phase 1 in a new chat, Opus 5.5 at Extra high. |
| 27 Sep 2026 | Phase 1 | Done; results in §3b. `cxvr_control_panel_qt.py` (4,337 lines) and port kit v1 shipped, every suite passing from a clean unzip. The first upload was an older Tk panel (3,321 lines, session 3); the frozen session-4 file was then uploaded and used. Findings about the shared logic in §14; nothing changed in either file for them yet. Next: your double-click check on the laptop, then Phase 2 in a new chat (Opus 5.5 at Extra high). |
| 30 Sep 2026 | Audit | Whole-project audit: `cxvr_code_audit_2026-09-30.md` (2 High, 13 Medium, 31 Low, 4 Qt-only, 4 kit). H1 (the headtracking lock inherited by the adb server) reproduced with a real adb; the rest from reading. Nothing changed in either file. |
| 30 Sep 2026 | Fix plan | `cxvr_audit_fix_plan.md` written at Max effort: four batches, fixes in both panel files, before Phase 2. Decisions A1–A8 assumed, including §14 items 1–3. Next: Batch 1 at Extra high. |

Mirror log (Tkinter fixes mirrored into Qt). Each audit-fix batch adds a line here, with the Tk panel's new md5.

| Date | Fix | Tk md5 | Qt md5 |
|---|---|---|---|
| 6 Oct 2026 | B0 (C1): `< /dev/null` on the four backgrounded subshells in `apply_headtracking_fix`; `stdin=DEVNULL` in `sync_files.run_adb`. Both panels; `EMBEDDED_SCRIPTS` byte-identical; line counts unchanged (3,869 / 4,337). | `d28e612be8d76cb6cbe79a0d18ac4056` | `c8478e43095000002534df0581220b24` |

**Open decisions (for you):**
- The fix plan's §2: A1–A8 are assumed; say if you want any changed.
- §14 items 1–3: covered by the fix plan (B1.4, B1.5, B1.6) under A8.
- Still assumed from Phase 0: D1–D5. Still unconfirmed: the double-click of the updated preview, which
  features are marked tested on the laptop, and whether headsets ever use headphones at shows.

## 14. Findings about the shared logic (Phase 1, 27 Sep 2026)
The port kit found these in code the Qt panel copies from the Tk panel. Both panels behave identically,
and the tests pin today's behaviour until a fix is approved and mirrored.
1. **A watchdog that dies within about 0.1 s of starting keeps showing as Running**, and stays listed under
   Background tasks. `_refresh_toggle_state` compares against a cached snapshot that `_start_toggle`
   never updates. Reproduced on the Tk panel (scenario `heartbeat_dies_within_one_tick`). Proposed fix,
   about 6 lines: compare each switch with `toggle_procs` on every tick instead of trusting the cache.
2. **`timeout`-wrapped adb calls outlive the panel by up to about 20 s.** Coreutils `timeout` moves itself
   into its own process group, so `kill_process_group` (a killpg of the script's group) misses it. It
   stays in the script's session and ends when its timeout runs out. Measured on both panels (11
   stragglers, gone after 20 s). Until then, a queued wake keyevent, for example, can still reach a
   headset after the panel has closed. Proposed fix: for a forced kill, also signal every process in the
   child's own session, reusing the `/proc` session lookup `end_terminal_session` already has.
3. **Tk only:** a mouse-wheel notch over a read-only headset dropdown changes the target (verified: ALL →
   .28 → .31). Actions with a confirmation name the scope, but Wake, Check volume, presets other than
   Mute, and Set Volume don't ask. Already fixed in Qt by design (§6.10).
4. **Show Mode's scope** is narrower than the preview banner and the old §9 step 5 said. Only
   `overheatWatchdog.py` and `blackScreenProbe.py` read `show_mode` (and `sync_in_progress`). The Tk
   caption was right; the Qt banner now says the same. §9 is corrected.

**30 Sep 2026:** items 1–3 are planned in `cxvr_audit_fix_plan.md` (B1.4, B1.5, B1.6). Item 4 changes
with Batch 2: the Headtracking watchdog and Popup recovery will also read both brakes (B2.1, B2.3), and §9
step 5 will be updated when that ships.

---

## Appendix A — Project instructions (paste-ready)
The user pastes this into the project's instructions. This is the text as of 27 Sep 2026; update it again
at cutover.

```
# CXVR Fleet Control Panel — project instructions

## Context
You're helping maintain the control panel for CulturalXchange.org's mobile VR theater: a fleet of about 70
Oculus Go headsets running the Headjack app `com.CulturalXchange.BibleSchool`, managed over wireless ADB
(172.16.16.0/24, port 5555). The panel is one self-contained Python file that embeds its helper scripts as
strings in `EMBEDDED_SCRIPTS`.

A port from Tkinter to PySide6 (Qt) is in progress. Until cutover there are two panel files:
- `cxvr_control_panel.py`: the Tkinter panel (stdlib only). Frozen: it stays the production tool until the
  Qt panel passes a rehearsal (a simulated show with the whole fleet). Critical fixes only, each mirrored
  into the Qt file and logged in the plan.
- `cxvr_control_panel_qt.py`: the PySide6 port (created in Phase 1).

Read `cxvr_pyside6_port_plan.md` (phases, status, intentional differences) and
`cxvr_project_state_summary_v4.md` (what the panel does) in project knowledge before starting.

The user's laptop: Cinnamon on X11, with Python 3.11.2 (both the system Python and the venv at
`/home/user/.pyvenv`) and PySide6 6.11.2 in that venv. The user starts the panel by double-clicking the .py
file in Thunar, which runs it with the system Python. So the Qt panel relaunches itself with
`~/.pyvenv/bin/python` when PySide6 is missing.

## Start of every chat
- Work from the files the user uploads: the frozen Tkinter panel, the latest port kit zip and, from Phase 2
  on, the Qt panel. If one is missing, ask for it. Never reconstruct a file from a summary or from memory.
- If the task touches a gated feature, ask which features the user has marked tested (stored in their
  config, not in the file).

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
4. Long conversations. Once a chat gets long (30 exchanges, or several large code blocks), suggest
   starting a new chat once, and offer to upload an extensive hand-off summary file for the next chat to pick up from.

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

## Engineering workflow
- Embedded scripts: extract with `ast.literal_eval`, edit and test the standalone copy, re-embed by exact
  `repr()` replacement (assert exactly one match), then verify byte-exact embedded vs standalone and that
  every other embedded script is unchanged. Until cutover, `EMBEDDED_SCRIPTS` must be byte-identical in both
  panel files.
- Panel methods: locate them by AST line range and replace whole methods; use exact-match replacements
  (assert count == 1) for small edits; check afterwards that no method is defined twice.
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
  - Test `sync_files.py` with its monkeypatch harness.
- Ship by copying to `/mnt/user-data/outputs/` and presenting the files (the panel file and the port kit
  zip). Never ship anything untested; if work is cut short, say exactly what's verified and what isn't.

## UI conventions (Qt panel)
- Build pages from the shared components: Card, Caption, InfoButton with the `HELP` dict, Collapsible,
  ToggleRow / ToggleSwitch, ModePill, DevicePicker, TestingBanner.
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
```

## Appendix B — Inventory of the current panel (27 Sep 2026)
- **File:** 3,869 lines, 409 KB; `ControlPanel` has 153 methods (3,036 lines).
- **Menus:** Main, Connect, Sleep / Wake, Volume, Power, Heartbeat, Content Sync, Delete Video, Debug
  Tools, Screen Capture, Testing (plus the Testing pages for Power, Sleep / Wake, Snapshot and Terminal).
- **Actions:** 33 `action_*` methods.
- **Background tasks:** `htWatchdog`, `stayAwake`, `keepalive`, `popupWatchdog`, `overheatWatchdog`,
  `blackScreenProbe`, `heartbeat`, plus batch preview and the ADB traffic log.
- **Gated features (7):** `power.reboot`, `power.poweroff`, `sleepwake.overheat_watchdog`,
  `sleepwake.blackscreen_probe`, `delete_video.delete`, `debug.capture_snapshot`, `terminal.shell`.
- **Settings:** 53 settings variables; 27 config keys read, 22 of them saved by `_save_settings`.
- **HELP entries:** 19.
- **Log-queue message kinds (7):** `line`, `done`, `watchdog_summary`, `batch_status`,
  `screencap_status_refresh`, `term_data`, `term_exit`.
- **Tk touchpoints in the logic:** 38 message boxes, 12 confirmations, 3 file pickers, 9 toggle relabels,
  3 settings read from worker threads (full feed, taskbar grouping, title-bar height).
- **Embedded scripts by size:** `sync_files.py` 102 KB, `massConnect.sh` 30 KB, `delete_video.py` 14 KB,
  `blackScreenProbe.py` 13 KB, `overheatWatchdog.py` 10 KB, `volumeNormalize.sh` 9 KB,
  `captureDiagnostics.sh` 7 KB, and eight small shell scripts.

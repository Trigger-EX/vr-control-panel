# CulturalXchange VR Fleet Management — Project State Summary (v4)

Supersedes v1–v3. It lives in project knowledge, next to `cxvr_pyside6_port_plan.md`. It is self-contained:
v3's still-valid content is carried forward verbatim below. Session 4 (27 Sep 2026) is new.

---

## Quick orientation

- Fleet of **Oculus Go headsets** for CulturalXchange.org, a mobile VR theater. App:
  `com.CulturalXchange.BibleSchool` (built into the panel as `APP_PACKAGE`), built on the **Headjack** VR
  platform (Unity).
- Wireless ADB over `172.16.16.0/24`, port 5555. Shows run about 70 headsets.
- **The user's laptop:** Cinnamon on X11, Thunar, Python 3.11.2 (both the system Python and the venv at
  `/home/user/.pyvenv`), and PySide6 6.11.2 in that venv. The user starts the panel by double-clicking the
  .py file in Thunar. **All code must run on Python 3.11**, the Tkinter panel included; it passes its test
  suites on 3.11.
- Deliverable today: **`cxvr_control_panel.py`** (3,869 lines): a self-contained Python/Tkinter GUI, stdlib
  only. It embeds 15 helper scripts as strings in an `EMBEDDED_SCRIPTS` dict and writes them to
  `~/.cxvr_control_panel/embedded_scripts/` at launch (all in one folder, so the Python ones can
  `import sync_files`). Config: `~/.cxvr_control_panel/config.json`.
- **A PySide6 port is planned** (`cxvr_pyside6_port_plan.md`). During the port, the Tkinter file is frozen
  (critical fixes only) and stays the production tool until the Qt panel passes a rehearsal.
- **Always ask the user to upload the current panel file(s)** rather than reconstructing them from a
  summary.

## The user's standing rules (apply to all future work)

1. **GUI only.** The user operates entirely through the panel. Every CLI flag added to an embedded script
   needs a matching GUI control, or it's unreachable.
2. **Untested features go under Testing.** Anything new — or materially changed — that the user hasn't
   confirmed on real headsets must be added to `GATED_FEATURES` and the Testing hub (see below), not placed
   straight into its normal menu. It moves to its normal home only when the user clicks Mark tested.
3. **Stop and ask for a stronger model** when a step would benefit greatly from one (creative/design work,
   safety-critical detection logic, large risky refactors). Say which model and which **effort level**.
   Guidance used so far: design/planning → Opus 5.5 at Max; big builds → Extra high; small bounded fixes →
   High is fine.
4. **Long-conversation note.** Once a conversation gets long (~15–20 exchanges or several big code blocks),
   suggest starting a new chat, once, with a summary like this one.

---

## Development workflow

To edit an embedded script:
1. Copy the panel file to a working directory.
2. Extract `EMBEDDED_SCRIPTS` with `ast.parse` + `ast.literal_eval` on the assignment (reliable; avoid regex).
3. Edit the standalone copy and test it before re-embedding.
4. Re-embed by replacing the old entry's exact `repr()` with the new content's `repr()` (assert the old one
   occurs exactly once).
5. **Verify byte-exact** embedded vs standalone, **and** assert every other embedded script is unchanged.
6. `python3 -m py_compile` + `python3 -m pyflakes` on the script and the panel.
7. Copy to `/mnt/user-data/outputs/` and present it.

To edit panel methods: locate them with `ast` (method name → `lineno`/`end_lineno`), replace whole methods by
line range bottom-up, and use exact-match string replacement (assert count == 1) for small edits. After any
change, assert there are no duplicate method definitions.

### Testing infrastructure

**Preferred now: real Tkinter under Xvfb.** `apt-get install -y python3-tk`, then
`xvfb-run -a -s "-screen 0 1600x1200x24" python3 test.py`. A shared `harness.py` loads the panel with
importlib and stubs, *before* constructing `ControlPanel`:
- `pm.popen_in_own_group` → records the command, returns a fake process with an empty `stdout` iterator
- `pm.kill_process_group` → records only. **Always stub this:** a fake process with `pid=1` once made the real
  function send SIGINT to the test's own process group.
- `pm.threading.Thread` → no-op, or a synchronous runner when a test needs the worker to execute
- `pm.subprocess.run` → canned `adb devices` output. This patches the global `subprocess` module, so keep a
  `real_run` reference for anything that genuinely needs it (screenshots).
- `pm.messagebox.*` → record calls; `askyesno` returns a controllable answer. If a test swaps in a plain
  lambda, restore the recorder afterwards or later dialog assertions silently see nothing.

Three test scripts proved their worth this session:
- **t_render / t_fit** — show every screen, compare `actions_container.winfo_reqwidth()` against the
  visible canvas width, and screenshot with ImageMagick (`import -window root -crop WxH+0+0`). Run at the
  default **920×760** and the minimum **780×640**; both must need no sideways scrolling.
- **t_behavior** — 39 click-through checks using `button.invoke()` on real widgets: watchdog start/stop
  relabeling, headset targeting per action, confirmation wording, collapsibles, log hide persistence,
  Testing hub, delete-video and screen-capture combos.
- Noise to ignore: destroying a second test `Tk()` root prints `invalid command name "…_poll_log_queue"`
  because its `after` timer was still scheduled.

The older **fake-tkinter stub** (`sys.modules` injection) still works for quick headless checks but misses
geometry and real widget behavior; add stub widgets as needed (`Combobox`, `Spinbox`, `showwarning` all had
to be added).

`sync_files.py` harness (unchanged from v2):
- **`sync_files.py` harness**: monkeypatch `sf.shell`, `sf.run_adb`, `sf.device_alive`,
  `sf.batched_size_check`, `sf.get_free_bytes`, `sf.push_one`, `sf.load_device_state`,
  `sf.save_device_state`, `sf.remote_size_manifest` with fakes returning canned
  `subprocess.CompletedProcess` objects. Enables full `sync_device()` integration tests with no devices.
- **Fake-clock pattern** for anything time-based: inject a `time_func` that advances a counter, so
  timeout/stall logic is tested deterministically with zero real waiting.

**Testing keeps catching real bugs that reasoning and pyflakes miss** — keep testing rigorously.

---

## Session 4 — built-in app package, terminal, layout freezes, PySide6 decision (all shipped and tested)

### App package built in
- `APP_PACKAGE = "com.CulturalXchange.BibleSchool"` sits near the top of the file. It was confirmed with the
  user's `adb shell pm list packages`. An Android package ID never changes across app updates; a different
  ID would be a different app.
- The Content Sync "App package" field is gone, and a caption shows the built-in value instead. `package` was
  removed from `DEFAULT_CONFIG`. If an old saved value differs, the log says so at startup.
- Everything that needed the package reads the constant: `_sync_cmd`, `_delete_video_cmd` and the popup,
  overheat and black-screen watchdogs. The old "package required" dialogs are gone.
- New guard, `_remote_target_matches_package`: sync and delete refuse a Remote target inside a different
  app's `/Android/data/<pkg>` folder.
- Verified: the commands are byte-identical to the old panel's (with the field filled in) across 6 sync
  scenarios, delete and the 3 watchdogs (18/18). The embedded scripts are unchanged; they still take
  `--package`, and the panel always passes the constant.

### Built-in terminal (gated: `terminal.shell`)
- Sits under the live log and is visible from every page, once marked tested or after Testing › Terminal ›
  Show terminal (for that session only). Its header strip has a status, a "?" and Hide/Show, persisted as
  `terminal_hidden`.
- A bar on the right has the "Shell on" dropdown (This computer, plus connected headsets; read-only),
  Refresh, Open, Ctrl+C and Clear.
- Backend: a real pty (`pty.openpty`) started with `setsid -c`, so Ctrl+C reaches the running job. `TERM=dumb`
  and pagers set to `cat`.
  - `TerminalStream` strips colour and title escape sequences (holding back sequences and UTF-8 characters
    split across reads), redraws lines on carriage return and handles backspace.
  - Output is capped at 5,000 lines, and the pty size follows the widget.
- Local sessions run `bash -i` in the home folder; headset sessions run `adb -s <serial> shell`.
- The command line has history (Up/Down); Ctrl+C sends ^C unless text is selected; Ctrl+D on an empty line
  ends the session; Ctrl+L clears. Input is masked while a local program turns echo off in canonical mode (a
  password prompt), and masked lines never go into history.
- Ending a session (opening another, closing the panel, or unmarking the feature) sends SIGHUP and then
  SIGKILL to every process in the terminal's session, found through `/proc` session IDs. It first confirms the
  session belongs to the shell and isn't the panel's own. This fixed a bug where `sleep 300 &` survived
  closing the panel.
- Show Mode and the sync brake don't apply to the terminal; its "?" says so.
- Tests: 42 behaviour checks on a real bash pty under Xvfb (a fake adb stood in for headset shells) and
  12 stream checks. **Not yet tried on a real headset.**

### Layout freezes fixed
1. **Caption width feedback.** Captions now request `width=1`, so their size comes only from their parent.
   Before, a stale wraplength request looked like horizontal overflow once the vertical scrollbar appeared,
   and the two scrollbars could flip each other forever (Volume menu).
2. **Vertical scrollbar feedback.** The scrollbar's column now always reserves its width
   (`columnconfigure(1, minsize=…)`). Before, the cycle was:
   - showing the scrollbar narrowed the content;
   - a caption re-wrapped onto an extra line, which pushed the content past the visible height;
   - hiding the scrollbar reversed it, and the loop repeated forever.

   Seen at 920×640 with the log hidden and the terminal shown, on Volume: 295 px of content without the bar,
   309 px with it, 305 px visible. The mechanism was already in the original layout code.
3. **Connect needed 798 px at 780 px wide, even in the v3 file.** v3's fit test set the window size before
   constructing `ControlPanel`, and `__init__` resets it to 920×760, so 780 was never actually tested (measured:
   906 px visible instead of 766). The three button subtitles were shortened, and Connect now needs 612 px.
   **Test lesson: set the geometry after construction.**
- Verified: a sweep of 15 menus × 2 widths × 5 heights × log and terminal each shown or hidden (600 renders),
  plus 900 live resizes in 2 px steps. No hangs and no sideways scrolling.
- Not fixed (pre-existing): at 780 px wide, the top strip clips "Background tasks".

### Screen Capture redesign (approved; to be built in the port's Phase 4)
- A headset grid: buttons labelled by the last number of the IP, reflowing with width, with a filter box and
  attention colours. Prev/Next, the arrow keys and the mouse wheel step through headsets; stepping replaces the
  open view in place; double-click opens a view.
- Double view uses one connection: scrcpy `--v4l2-sink=/dev/videoN` keeps its own window, and a view-only
  ffplay window shows the same video on the second monitor. The user prefers view-only to a second scrcpy
  session, which would double the headset's encoding load (heat) and the WiFi use.
- The user's environment:
  - scrcpy 3.3.4, an X11 session, and ffplay at `/usr/bin/ffplay`.
  - `/dev/video0` and `/dev/video1` exist; almost certainly the built-in webcam, so v4l2loopback isn't
    installed yet.
  - `xrandr --listmonitors` showed only eDP-1 at 1920×1080 (the second monitor wasn't connected then).
- Setup needed: `sudo apt install v4l2loopback-dkms`, then load the module with
  `video_nr=10 card_label="CXVR second view"`.

### PySide6 preview and the port decision
- `cxvr_pyside6_preview.py` is a look-only PySide6 mock-up (mock data; it never runs adb). It shows Screen
  Capture and Sleep / Wake, with the top strip, the sidebar and the log/terminal tabs. Renders were verified
  offscreen at 1280×800 and 1920×1080, and 12 interaction checks pass.
- **The user decided to port to PySide6.** PySide6 is installed in `/home/user/.pyvenv`. The plan is
  `cxvr_pyside6_port_plan.md` in project knowledge. The Tkinter panel is frozen (critical fixes only) until
  cutover.
- Tested while planning:
  - Python signal handlers don't run while Qt's event loop is idle, so SIGTERM cleanup needs a periodic
    Python timer.
  - Saving the QDockWidget layout needs object names on the docks.
  - QtTest ships with PySide6-Essentials.

### Workspace notes
- The cloud workspace was reset mid-session once, and the working copy was lost. Everything was rebuilt from
  the original upload using replayable edit scripts. Keep edits as scripts, and deliver working files early.
- In the workspace, only `/usr/bin/python3.12` had tkinter; the default `python3` (3.11) didn't. Use uv's
  standalone Python 3.11 instead (`pip install uv`, `uv python install 3.11`): it includes Tkinter and matches
  the laptop's minor version.
- Test scripts from this session (kept in port kit v0): `harness.py`, `t_stream.py` (12), `t_term.py` (42),
  `t_pkg.py` (18), `t_behavior.py` (33), `t_cell.py` with `run_sweep.sh` (size and state sweep), `t_fine.py`
  (live resize), `t_loop.py` (scrollbar trace).

---

## Session 3 — what was built (all shipped, tested, byte-verified)

### Targeted power (feature 1)
- `rebootAll.sh` and `powerOff.sh` now accept an optional `[device_serial]`, matching `sleepAll.sh`,
  `wakeAll.sh` and `screenRefresh.sh`.
- Power Management has a headset dropdown. The confirmation text is conditional: "reboots headset X" for a
  single target, "EVERY connected headset" only when that's true.

### Diagnostic Snapshot — `captureDiagnostics.sh` (new, read-only)
Flags `--device`, `--repeat`, `--interval`, `--out-dir`, `--no-screencap`. Writes
`~/.cxvr_control_panel/snapshots/<serial>_<timestamp>/` containing `dumpsys` power, display, the **full**
window list, activities, media_session, audio, SurfaceFlinger (+ layer list), thermalservice, battery, a
2000-line logcat tail, `getprop`, an optional screenshot, and a `SUMMARY.txt` digest. Every call is wrapped in
`timeout`. Repeat passes exist to catch a transient dialog. Lives in Debug Tools.

### Two safety brakes on automated actions
Plain files, so separate daemon processes see them immediately without a restart:
- `~/.cxvr_control_panel/show_mode` — **Show Mode** checkbox on the main menu; survives restarts.
- `~/.cxvr_control_panel/sync_in_progress` — written by `_run_command` whenever the command contains
  `sync_files.py`, removed in a `finally` (verified to clear even if the launch crashes).
Both daemons below check these each cycle: they keep monitoring and logging, but send nothing. Verified end
to end that a daemon suppresses during a sync and resumes the moment it ends.

### `overheatWatchdog.py` (new; feature 4)
- Dismisses with **BACK** (keyevent 4 — what scrcpy's right-click sends), never HOME. BACK inside the app
  could exit playback, so it acts **only on a positive match**, never as a fallback. That's why it's a
  sibling of `popupWatchdog.sh` rather than a flag on it.
- Scans the **full** `dumpsys window windows` list (catches non-focusable overlays that a focus-only check
  misses) plus `logcat -d -t 200`. Lines containing the app's own package are excluded.
- Ships **observe-only**; `--arm` enables sending. Broad `DEFAULT_MATCH_PATTERN`
  (`thermal|overheat|too hot|temperature|cooling|heat`) — right for observing, wrong for acting. Narrow it
  from real evidence before arming.
- Per-device cooldown file, `--interval`, `--cooldown`, `--state-dir`, `--parent-pid`. Unreadable devices
  produce no action. Logs to `~/.cxvr_control_panel/logs/`.

### `blackScreenProbe.py` (new; feature 3, phase E)
- Samples each headset every `--interval` (default 20 s): display power state, wakefulness, foreground app,
  audio active, battery temperature. Writes a per-run CSV to `~/.cxvr_control_panel/probe_data/`.
- The key insight: **"display powered OFF while the app is in front" is unambiguous** — the black frames
  between films happen with the display ON. That's the only verdict that can ever act
  (`display_off_during_app`). An unrecognized `dumpsys` format parses as unknown, never as OFF.
- **Case B (display on but rendering black) is recorded, never acted on**, regardless of flags. Choosing a
  threshold that separates it from a long film transition needs the probe's own CSV data from a real show.
- `--arm-display-off` (off by default), `--consecutive` (3), `--recovery wake|cycle` (keyevent 224, or
  223 then 224), `--cooldown` 120.
- Both daemons import `sync_files` for adb, logging and device helpers, following `delete_video.py`'s pattern.

### Batch window grouping (feature 2)
Batch-preview scrcpy windows get `SDL_VIDEO_X11_WMCLASS` / `SDL_VIDEO_WAYLAND_WMCLASS = "cxvr-batch"` via
`_scrcpy_env(group=...)`; single windows opened with Connect are deliberately left ungrouped. Checkbox in
Screen Capture, persisted as `group_batch_windows`. **Not verified on the user's desktop** — taskbars group by
window class, but whether hover previews appear depends on the DE. If it doesn't work, nothing breaks.

### The Testing gate
- `GATED_FEATURES` (module level) maps each gated key to (category, label): `power.reboot`, `power.poweroff`,
  `sleepwake.overheat_watchdog`, `sleepwake.blackscreen_probe`, `delete_video.delete`,
  `debug.capture_snapshot`.
- Marked-tested keys persist in config as `tested_features` (empty on a fresh install). Helpers:
  `_is_tested`, `_mark_tested(key, refresh)`, `_unmark_tested`.
- Normal menus hide untested items and show a short "in Testing" notice instead.
- **Main Menu › Testing** lists every untested item with **Open** and **Mark tested**. `_testing_items()`
  defines the grouping, destinations and openers — add new gated features there too.
- Actions behave identically whichever page triggers them; the gate only changes visibility.
- Bug fixed during the layout rebuild: Capture Diagnostic Snapshot previously couldn't be *run* from Testing,
  only marked tested. It now opens a working page.
- **Ask the user which features they've since marked tested** — that lives in their config, not the file.

### Layout rebuild — "Option A: sectioned cards"
Chosen by the user from mockups on the design canvas: https://claude.ai/artifact/WMJB4y7Ps3aDpy3psGpejh
(current layout, three options, and Option A applied to every submenu).

Window chrome:
- One **top strip** (status numbers in a 2×2 grid, background tasks, Stop all tasks / Interrupt script /
  Kill ADB server), a **nav row** (‹ Main Menu + title), the scrollable **actions area**, and a **fixed
  7-line log** with Clear and Hide/Show (hidden state persisted as `log_hidden`).
- Root cause of the old cramped feel: the log was packed with `expand=True`, splitting spare height 50/50
  with the menu. Menus now get ~485 px on the default window instead of ~200 px; Content Sync went from
  ~1,600 px of content to ~580 px.
- Scrollbars show only when needed. The canvas window's width is forced to the visible width, but its
  **height is left natural** so content that grows later (re-wrapped captions, opened sections) is never
  clipped.

Shared components (use these for anything new):
- `_card(title, right=)` — bordered section with a tinted header; `right` puts a small control in the header.
- `_caption(...)` — muted text that re-wraps to its width. Only place it filling its parent (`pack fill=x`
  or `grid sticky=ew`), otherwise re-wrapping can feed back into its own width.
- `_info_button` / `HELP` dict — the original long explanations, moved verbatim behind "?" buttons.
- `_collapsible(key, title, summary)` — starts collapsed; open state remembered for the session.
- `_toggle_row(...)` — status dot, Running tag, caption, inline settings, "?", and a `ToggleButton`.
- `ToggleButton` — normalizes any "Start …"/"Stop …" text to short labels and updates its row. This keeps
  every pre-existing relabeling call site (`_start_toggle`, `_stop_all_toggles`, batch preview, debug log)
  working unchanged.
- `_target_row` / `_device_picker` — the one headset dropdown (+ Refresh) used everywhere; `ALL_DEVICES_LABEL`
  resolves to "no serial" via `_resolve_target`. Sleep/Wake and Volume no longer use free-text boxes.
- `_mode_pill` (Observe only / Armed), `_testing_banner`, `_mark_tested_right`, `_back_to_testing`.
- Styles in `_apply_styles` (ttk `clam`, `UI_*` palette). One `Primary.TButton` per screen;
  `Danger.TButton` for Power Off and Delete Video; `Small`, `Nav` and `Info` buttons override clam's
  9-character minimum width.

Behavior fixes that came with it:
- `_refresh_toggle_state()` runs in the log poll loop, so a watchdog that exits on its own now updates its
  row and the Background tasks label (previously both stayed stale).
- `_register` disables a button if an action is already running, so a menu opened mid-action comes up
  disabled.
- Headset selections, volume level and screen-capture device are created once in `_init_settings_vars`, so
  they survive switching menus.

Layout rules for future edits: inside `actions_container`, cards are packed; within any one card body use a
single geometry manager; keep each screen's natural width under the visible width, verified with the fit test
at 920×760 and 780×640. Rendered with DejaVu Sans under Xvfb — worth a look on the user's own desktop.

---

## Session 2 — `sync_files.py`, `delete_video.py` and panel fixes (carried forward from v2, still accurate)

Everything here still applies, except that the panel-layout measurements under "Control panel fixes"
predate the session 3 layout rebuild — the watchdog-registration race fix there is still current.

### `sync_files.py` — safety fixes

1. **App-root prune scoping.** In `--content-is-app-root` mode the *local* scan was correctly limited to
   `files/Video`/`files/Media`, but the *remote* scan still walked the whole app root, so anything else
   under it that wasn't on the protected list counted as "extra" and would be deleted by `--prune`.
   Now the freshly-scanned remote manifest is filtered to those same two subtrees before diffing.
2. **App-root + stale remote-target guard.** `--content-is-app-root` combined with a `--remote-target`
   still pointing at `.../files/Video` or `.../files/Media` would push content one level too deep
   (`files/Video/files/Video/...`) and then `--prune` would see the real content as extra and delete it.
   Now refused at startup with an explanatory error, and mirrored client-side in the GUI's `_sync_cmd`.
3. **Prune delete count** only increments when `rm` actually succeeds; failures are logged.

### `sync_files.py` — push reliability

4. **Size-scaled push timeout.** The flat `ADB_TIMEOUT_PUSH = 600` killed a legitimately-progressing
   7.6GB transfer on all 5 headsets at almost exactly 600s each (confirmed from real logs). Replaced with
   `push_timeout_for(size_bytes)`: floors at `PUSH_TIMEOUT_FLOOR = 600`, otherwise assumes a pessimistic
   `PUSH_TIMEOUT_MIN_MBPS = 5` and multiplies by `PUSH_TIMEOUT_SAFETY_FACTOR = 2`. The 7.6GB file now gets
   ~3048s. Used by both `push_one` and the bandwidth diagnostic's `timed_push`.
5. **Stall detection.** Because that timeout can now be ~51 minutes, a genuinely dead transfer would hang
   far too long. `_push_with_stall_detection()` runs `adb push` via `_spawn_push()` (isolated for testing)
   and polls the remote file's growing size every `PUSH_STALL_CHECK_INTERVAL = 30`s; if it hasn't grown in
   `PUSH_STALL_TIMEOUT = 90`s, the process is killed and the attempt fails early, distinctly logged as
   `STALLED`. `PUSH_POLL_INTERVAL = 5` for checking whether the process already exited.
   **Important detail:** stderr goes to a real temp file, not `subprocess.PIPE` — a chatty progress bar
   could otherwise fill a pipe buffer and block the child, causing a self-inflicted stall.
   These constants are not yet exposed as CLI flags or GUI controls.

### `sync_files.py` — free-space accounting

6. **Post-failure space re-check via `df`.** The running free-space estimate only changed on success, so a
   failed push's leftover bytes were never accounted for and later files in the same batch were evaluated
   against a stale figure. Now re-queries `get_free_bytes()` after any failure (authoritative; counts space
   held by deleted-but-open files, which a `stat` on the path cannot see) and logs the visible-vs-invisible
   split.
7. **Failed-push record + reboot advice.** Per-device `devices/<sanitized-serial>.failed_pushes.json` in the
   state dir, written on failure and cleared on success — deliberately separate from the trusted-state
   manifest, which is only saved on fully clean runs. When a later run skips a file for low storage *and*
   that file failed before *and* nothing is visible at its path, the log says to reboot that headset rather
   than suggesting `--prune`. The end-of-run summary names affected headsets separately from genuinely-full
   ones (`REBOOT-SUGGESTED(space held by failed push)`).

### `sync_files.py` — Headjack install registration (v3.local)

8. **Registration on push.** Content pushed directly over ADB bypasses Headjack's own downloader, which is
   normally what writes the "installed" record, so files were present and playable while the Operator app
   reported them as not downloaded. `register_pushed_content_in_v3local()` fills a still-empty `"v"` entry
   for a content ID; it **never** overwrites an entry that's already non-empty (Headjack matches by folder
   ID, not filename). Mirrors `find_and_clean_stale_v3local`'s read/validate/backup/write approach: BOM
   preserved, on-device backup `v3.local.bak.<timestamp>`, own JSON validated before pushing, graceful skip
   with a log line if `v3.local` is missing or unparseable.
9. **Backfill, not just fresh pushes.** The first version only considered files pushed *in that run*, so
   content correctly pushed before the feature existed stayed unregistered forever (it never re-entered
   `to_push`). `register_all_known_content()` now runs against everything currently known-correct on the
   device, **including on the "up to date, nothing to do" fast path** — which is the path a healthy device
   hits on almost every run. Idempotent: writes nothing once all known IDs are registered.
10. **Dry-run accuracy.** Registration was short-circuited entirely under `--dry-run`, so a dry run reported
    nothing while the following real run registered 53 entries. It now performs the same read-only check and
    reports `[dry-run] would register N content ID(s)`, writing nothing. Log wording also corrected — it
    said "newly-pushed" even when `pushed=0` and the work was pure backfill.
11. **Package derivation.** `derive_package_from_remote_path()` pulls the package out of a
    `/sdcard/Android/data/<package>/...` path, so `--clean-stale-metadata`, `--check-catalog-ids` and
    registration all work when only `--remote-target` was given (the user's actual command shape). Previously
    these silently skipped.
12. New flag `--skip-install-registration` (off by default) + GUI checkbox.

### `sync_files.py` — console output

13. The long "N local file(s) match Headjack's own device-specific bookkeeping..." warning printed **once per
    device** (5x per run) even though it's purely a function of the local content folder. Now printed once per
    run, right after the local-scan line, split across two shorter lines.
14. `Log.blank()` added; blank lines at section boundaries (after startup info, before the summary, before
    trailing warnings — the last only when a warning actually exists).

### New embedded script: `delete_video.py`

Companion to `sync_files.py`; **imports `sync_files` directly** (all embedded scripts materialize into the
same directory, so this works) rather than duplicating adb/v3.local/state logic. Per headset it:
1. Checks both candidate on-device paths (app-root style and `files/Video`-direct style) and acts only on the
   one that exists; if both exist it refuses rather than guess.
2. Deletes the content-ID folder.
3. Clears that ID's `v3.local` install marker (blanks `"v"`, never removes the ID — matches how Headjack's own
   downloader behaves), unless `--skip-v3local-update`.
4. Drops matching entries from the trusted-state cache so a later *plain* sync re-pushes rather than trusting
   a stale record.

Flags: `--video-ids`, `--devices` (comma-separated or `ALL`), `--remote-target`, `--package`,
`--skip-v3local-update`, `--state-dir`, `--dry-run`.

GUI: new **Delete Video** menu — video dropdown (labels read from the local `files/App/*.v3` catalog, so
entries read `"@The Capitol Jan 6, 2021 (871t867...)"`; falls back to bare IDs if no catalog is found),
headset dropdown (live `adb devices` + "ALL CONNECTED HEADSETS"), dry-run **checked by default**, and a
confirmation dialog naming the exact video and target before any real delete.

### Control panel fixes

15. **Watchdog registration race.** `_start_toggle` spawned the process *inside* the background thread, but
    updated the "Background tasks" label immediately on the main thread — the label almost always won, and
    since nothing else refreshes it, the Status area could read "none running" indefinitely while the
    watchdog ran. Fixed by spawning on the main thread (`Popen` doesn't block; only reading its output does)
    and registering in `toggle_procs` before the thread starts.
16. **Sleep/Wake horizontal scrolling.** That menu required **3543px** — nearly double a 1920px screen.
    Cause: its help label was the only large label missing `wraplength=650`, so its longest unwrapped line
    (609 chars) became the container's minimum width, and the actions canvas correctly honored it with a
    horizontal scrollbar. Fixed; now 994px. Audited all 57 labels; the two other unwrapped ones (Power,
    Heartbeat) were also fixed for consistency. All menus now fit at 1280px and up; Content Sync's 1110px is
    legitimate content width, not a bug.

---

## Field findings (from real runs — not assumptions)

### Storage held by aborted transfers
After the 7.6GB timeout failures, two headsets showed ~6.4GB and ~6.3GB of unaccounted used space with
**no file visible at the target path**. Arithmetic (free-before minus successful pushes, vs. actual free)
matched the bytes a 600s transfer would have written. Best explanation: adbd deletes the partial file when a
push aborts, but a deleted file's space isn't released until every open handle closes, and the killed
transfer was never fully torn down on the device side. **The user confirmed a reboot released it.** This is
why the tool now advises rebooting rather than deleting content.

Note: stall detection kills the host-side adb client, which could in principle orphan space the same way.
Worth watching whether reboot suggestions start appearing after `STALLED` failures specifically.

### The catalog is authoritative; `v3.local` is not
The Operator app's "N/13" count comes from the **13 `Video` entries in `files/App/<app-id>.v3`**, not from
what's on disk and not from `v3.local`. The app appears to validate the actual file against the catalog's
expected filename/size for the active download profile — a registered `v3.local` entry is not sufficient on
its own.

### The `871t867donz61pdcs4ewanukhh7ajmk3` case (resolved, not a tool bug)
That video showed as unavailable despite the file being present, correct, and playable. Its catalog entry had
`DownloadProfileCurrent: 1000` (original quality) expecting `ORG_The_Capitol_Jan6_4K.mp4` at ~10.1GB, while
the actual staged file was a 5.0GB HEVC transcode. **Cause: the user's partner changed the profile setting in
the Headjack CMS.** Resolution is in the CMS, not in our tooling. Useful precedent: a CMS-side setting change
can invalidate already-synced content fleet-wide, and the symptom looks like a sync failure.

Five other catalog videos have no local source files — **intentional**, per the user; they're not currently
meant to be available. Expect 8/13, not 13/13.

### Headset friendly names ("Headset 403")
**Not stored on the headset.** Assigned in the Headjack Operator tablet app at pairing time and held in
Headjack's cloud records. Nothing under `/sdcard` contains them. A long-shot check was suggested but not yet
run by the user:
```
for s in $(adb devices | tail -n +2 | cut -f1); do echo "== $s =="; \
  adb -s "$s" shell settings get global device_name; \
  adb -s "$s" shell settings get secure bluetooth_name; done
```
If those return real names, wire them into every headset list in the panel. If not, IP:port is all that's
locally available, and any friendly-name feature would need a **manual mapping file** (serial → label) kept
by the user, which is a perfectly reasonable fallback worth offering.

### Local content folder composition
The SD-card clone at `.../Android/data/com.CulturalXchange.BibleSchool` holds 44 files: 15 real content files
(8 videos + 7 media) and 29 protected bookkeeping files. All 29 were verified programmatically to match an
existing `is_protected_headjack_file()` rule, so nothing slips through **for this tree** — but that list is a
blacklist, so a future Headjack/Unity update could add something unrecognized. `--content-is-app-root` remains
the structurally safer option (scan-scope allowlist rather than post-hoc filtering) and needs no other
changes given the user's current command shape.

Note: a headset pulled mid-session had **no** `manifest.tsv`/`pc_manifest.txt` — those appear to be artifacts
of whatever tool made the SD clone, not something Headjack requires on-device.

---

## Current state

**Files:** `cxvr_control_panel.py` (Tkinter, 3,869 lines; frozen for the port), `cxvr_pyside6_preview.py`
(mock-up; relaunches itself with the venv Python when double-clicked) and `cxvr_port_kit_v0.1.zip` (this
session's test scripts, the preview and the launch tests).

**Embedded scripts (15):** `massConnect.sh`, `sleepAll.sh`, `wakeAll.sh`, `stayAwake.sh`, `popupWatchdog.sh`,
`screenRefresh.sh`, `volumeNormalize.sh`, `rebootAll.sh`, `powerOff.sh`, `heartbeatMaintain.sh`,
`sync_files.py`, `delete_video.py`, `captureDiagnostics.sh`, `overheatWatchdog.py`, `blackScreenProbe.py`.
Unchanged in session 4.

**Menus:** Main (with Show Mode), Connect, Sleep / Wake, Volume, Power, Heartbeat, Content Sync, Delete Video,
Debug Tools, Screen Capture, Testing (plus Testing pages for Power, Sleep / Wake, Diagnostic Snapshot and
Terminal). The live log and the terminal are pinned at the bottom of every screen.

**Gated features (7):** `power.reboot`, `power.poweroff`, `sleepwake.overheat_watchdog`,
`sleepwake.blackscreen_probe`, `delete_video.delete`, `debug.capture_snapshot`, `terminal.shell`. Which ones
are marked tested lives in the user's config; ask.

**Config changes in session 4:** added `terminal_hidden`; removed `package` from the defaults.

No known open bugs apart from the pre-existing clipping of the top strip at 780 px wide.

## Next steps

1. **The PySide6 port.** Follow `cxvr_pyside6_port_plan.md`. Phase 0 is done; Phase 1 is next, in a new
   chat with Opus 5.5 at Extra high.
2. **Still waiting on field data** (unchanged from v3):
   - Overheat watchdog: capture a real overheat with Diagnostic Snapshot, narrow the pattern, observe, then
     arm and mark tested.
   - Black-screen probe: run it observe-only through a real show. If the display was ON during the fault,
     choosing the Case B threshold needs **Max** effort.
   - Taskbar grouping: the session is now known to be X11; still check `wmctrl -lx` with batch preview open.
   - Headset friendly names: run the `settings get` check, or fall back to a serial → label mapping file.
   - Mark features tested as they're confirmed, the terminal included.
3. **Still open from v2:** the multi-AP networking plan; grouping headsets by WiFi band in the bandwidth
   diagnostic; the stall-detection constants remain hardcoded (declined for now); `--devices` and
   `--skip-power-config` are deliberately session-only.

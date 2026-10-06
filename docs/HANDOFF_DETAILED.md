# CXVR control panel — detailed hand-off to Claude Code

Written 6 Oct 2026 at the end of the claude.ai chat that ran Phase 1 of the PySide6 port, the
whole-project audit, the audit fix plan, and the C1 investigation.

**Read first:** `CLAUDE.md` (rules), then this file. The full reference docs are in `docs/`.

---

## 1. Where things stand (summary)

| Track | State |
|---|---|
| Production panel | `cxvr_control_panel.py` (Tkinter, frozen). Unchanged since 27 Sep: md5 `fab822033fc7b83cf95b9bbf026ce6c1`, 3,869 lines. |
| PySide6 port | Phase 0 and Phase 1 done. `cxvr_control_panel_qt.py`: 4,337 lines, md5 `da5b000262234c5cf7f08d6be8ef7e57`, port kit v1 all green on 27 Sep. Phase 2 not started. |
| Audit (30 Sep) | Done: `docs/cxvr_code_audit_2026-09-30.md`. Findings: 2 High, 13 Medium, 31 Low, 4 Qt-only, 4 kit, plus **C1 (Critical)** added 3 Oct. |
| Fix plan (30 Sep) | Written at Max effort: `docs/cxvr_audit_fix_plan.md`. Hotfix B0 for C1, then Batches 1–4, all before port Phase 2. **Nothing implemented yet.** |
| C1 (3 Oct) | The automatic headtracking fix skips most headsets. Root cause found, reproduced, and the fix proven on a fake adb (`repro/c1_headtracking_stdin/`). **Hotfix B0 not yet approved or built.** |

Nothing in either panel file has changed since Phase 1. All the work since then is analysis, plans and
the reproduction.

---

## 2. The system

**The fleet.**
- About 70–80 Oculus Go headsets (80 were connected on 3 Oct), running Android 7.1.
- App: `com.CulturalXchange.BibleSchool`, a Headjack (Unity) app; `APP_PACKAGE` in the panel.
- Wireless ADB on `172.16.16.0/24`, port 5555. `CXVR_SUBNET_PREFIX = "172.16.16"` is the per-venue tunable.

**The laptop (Debian-based, Cinnamon on X11, Thunar).**
- Python 3.11.2 is the system Python. The venv `/home/user/.pyvenv` has PySide6 6.11.2.
- scrcpy 3.3.4 and `/usr/bin/ffplay`.
- The user double-clicks the panel `.py` in Thunar.

**The user operates only through the panel GUI** (rule 1).

**State on the laptop.** The panel and its scripts use these locations:

| Path | Purpose |
|---|---|
| `~/.cxvr_control_panel/config.json` | Settings, including `tested_features` (the Testing gate) |
| `~/.cxvr_control_panel/embedded_scripts/` | The 15 scripts, written by `materialize_scripts()` |
| `~/.cxvr_control_panel/logs/` | Script and daemon logs |
| `~/.cxvr_control_panel/snapshots/` | Diagnostic Snapshot output |
| `~/.cxvr_control_panel/probe_data/` | Black-Screen Probe CSVs |
| `~/.cxvr_control_panel/show_mode` | The Show Mode brake (a sentinel file) |
| `~/.cxvr_control_panel/sync_in_progress` | The sync brake (a sentinel file) |
| `~/.cxvr_massconnect/known_ips.txt` | Every headset address ever seen (host:port lines, never pruned) |
| `~/.cxvr_massconnect/massconnect.lock` (+ `.pid`) | The flock that serializes manual Connect and the watchdog |
| `~/.cxvr_headtracking_fix/` | One file per serial holding the last fixed boot_id; also `attempts_*` cooldown files and `batch_fix_*.log` |
| `~/.cxvr_popup_watchdog/` | Popup watchdog cooldown files |
| `~/.cxvr_sync/` | `sync_files.py` state: trusted manifests, per-device failed-push records, `logs/last_run_report.json` |

---

## 3. How the panel is built (what matters when editing)

**One file per panel.**
- `EMBEDDED_SCRIPTS` holds the 15 helper scripts as string literals. `materialize_scripts()` writes them to
  `~/.cxvr_control_panel/embedded_scripts/` at launch, and again on every `_script()` call (audit L25).
  They all sit in one folder, so the Python ones can `import sync_files`.
- **The 15 scripts:**

  | Script | Lines | What it does |
  |---|---|---|
  | `massConnect.sh` | 663 | Reconnect (known IPs or a full subnet scan), the WiFi never-sleep policy, the headtracking fix (sleep → wake once per boot, tracked by boot_id per serial), and the `--watchdog` mode the panel auto-starts. |
  | `sync_files.py` | 1,960 | Content sync, keepalive mode, bandwidth diagnostic, Headjack `v3.local` registration. |
  | `delete_video.py` | 310 | Imports `sync_files`. |
  | `blackScreenProbe.py` | 326 | Gated; observe-only by default. |
  | `overheatWatchdog.py` | 243 | Gated; observe-only by default. |
  | `volumeNormalize.sh` | 229 | Closed-loop volume set and check. |
  | `captureDiagnostics.sh` | 163 | Diagnostic Snapshot. |
  | `popupWatchdog.sh` | 112 | Sends HOME. |
  | Small scripts | — | `stayAwake.sh`, `heartbeatMaintain.sh`, `sleepAll.sh`, `wakeAll.sh`, `screenRefresh.sh`, `rebootAll.sh`, `powerOff.sh`. |

- **Processes.**
  - `popen_in_own_group` uses `start_new_session=True`. `kill_process_group` is a killpg of that group.
    Coreutils `timeout` makes its own group, so those children escape (port plan §14.2).
  - Watchdogs get `--parent-pid` and exit when the panel dies.
- **Log queue.**
  - Worker threads only `put` onto `log_queue`. The kinds are `line`, `done`, `watchdog_summary`,
    `batch_status`, `screencap_status_refresh`, `term_data` and `term_exit`.
  - Tk polls it every 100 ms in `_poll_log_queue`; Qt uses a QTimer, at most 2,000 items per tick.
- **One-shot actions** go through `_run_command` (one at a time; it writes `sync_in_progress` for syncs).
  **Watchdogs** go through `_start_toggle`; the Headtracking watchdog runs in "silent" mode, which forwards
  only its SUMMARY block.
- **The Testing gate.** `GATED_FEATURES` plus `_testing_items()`. There are 7 gated keys:
  `power.reboot`, `power.poweroff`, `sleepwake.overheat_watchdog`, `sleepwake.blackscreen_probe`,
  `delete_video.delete`, `debug.capture_snapshot` and `terminal.shell`.
- **The Tk panel's `ControlPanel`** has 153 methods.
  - Pages: Connect, Sleep / Wake, Volume, Power, Heartbeat, Content Sync, Delete Video, Debug Tools, Screen
    Capture, Testing, and the Testing sub-pages.
  - Its `__init__` resets the window size, so tests must set the geometry after constructing it.

**The Qt port.**
- **How the file is laid out.** The relaunch, the copied module blocks (constants, `EMBEDDED_SCRIPTS`, process
  helpers, terminal backend, palette and `HELP`), then the compatibility layer:
  - `Var` / `StringVar` / `BooleanVar`
  - the `messagebox` and `filedialog` shims (every confirmation defaults to No)
  - the widgets `Button`, `Entry`, `Check`, `Combo` (ignores the wheel), `SpinEntry`, `ToggleSwitch` and
    `VarSwitch`

  Then the design components (`Card`, `Caption`, `Collapsible`, `ModePill`, `ToggleRow`, `TestingBanner`,
  `ChipRow`, `StatCell`, `DockTitle`, `TargetRow`), then `ControlPanel(QMainWindow)`, then `main()`.
- **What was copied.** `port_kit/common/logic_map.py` classifies every Tk method: 83 copied verbatim
  (after the three substitutions), 34 rewritten, 2 dropped, 34 "later" (Phase 2/3 pages and the terminal
  UI).
- **Pages built so far:** Connect, Volume, Power, Heartbeat, the Testing hub and Testing › Power. The rest are
  placeholders.
- **Intentional differences** from Tk are listed in port plan §6 (14 items). Examples: sidebar navigation;
  confirmations default to No; the mouse wheel never changes a dropdown; a 20,000-line log; the panel opens on
  Connect.

**Port kit v1 (`port_kit/`).**
- `run_all.sh TK QT [OUT]` runs 12 steps: compile, integrity, stream ×2, Tk suites, differential (137
  scenarios), Qt behaviour (59), lifecycle (7), visual ×2, rollback and launch (7). All passed on 27 Sep.
- **Environment it needs:**
  - `apt-get install -y xvfb fonts-ubuntu libxcb-cursor0 imagemagick`
  - `pip install uv`, then `uv python install 3.11` (that's `PY311`; it includes Tkinter)
  - a venv: `uv venv ~/venv311 --python 3.11`, then `uv pip install --python ~/venv311/bin/python
    PySide6-Essentials==6.11.2 pyflakes` (that's `VENV_PY`)
  - `VHOME` for the launch tests (created automatically)
- **On the laptop,** the tests never touch real adb: everything is stubbed or uses fake adb binaries. Still
  check that no real headset is reachable from the test environment, or keep PATH ordering correct.

---

## 4. The critical bug C1 and hotfix B0 (do this first, once the user approves)

**What the user saw (3 Oct 2026).**
- A Full Scan connected 80 headsets; 72 needed the headtracking fix.
- After 3 attempts, 40 were confirmed and 32 FAILED. Every failure line read `sleep= wake= reachable=ok`;
  a few read `sleep= wake=ok`.
- The automatic fix "fails most of the time", while the mass Sleep and Wake buttons are reliable.

**Root cause (reproduced).** In `massConnect.sh` → `apply_headtracking_fix`:
- The detect, SLEEP, WAKE and reachability loops read the device list with
  `while IFS=$'\t' read -r … ; do ( … adb -t "$tid" shell … ) & done < "$pending_file"`.
- Bash doesn't give those backgrounded subshells `/dev/null` as stdin. `adb shell` forwards stdin to the
  device; `adb shell -n` is what disables that.
- So the first adb client to start reads the rest of the device list, and the loop hits EOF after roughly the
  first 10–15 headsets.
- Each retry reaches the next small batch. The rest never get SLEEP or WAKE, so their result files don't
  exist (`sleep=` empty).
- `adb get-state` doesn't read stdin, so the reachability loop reaches everyone (`reachable=ok`).
- The detect loop is vulnerable too, but its body is cheap, so it usually wins the race.
- Sleep All, Wake All and Sleep → Wake iterate `for d in $devices`: no stdin involved, so they're reliable.
- The watchdog uses the same function, so the automatic fix is broken there as well.

**Reproduction.** `repro/c1_headtracking_stdin/repro_c1.sh cxvr_control_panel.py` cuts the fix block out
of the embedded `massConnect.sh` and runs it against a fake adb that reads stdin like the real client.
Result on 6 Oct (the as-shipped counts vary a little from run to run):
- as shipped: `confirmed=11 failed=61  SLEEP sent: 11  WAKE sent: 78`
- with the fix: `confirmed=72 failed=0  SLEEP sent: 72  WAKE sent: 432`

**Fix (B0).**
- Add `< /dev/null` to each backgrounded subshell in those four loops in `apply_headtracking_fix`:
  - detect: the `( … ) &` at lines 247–265
  - SLEEP: line 345
  - WAKE: lines 359–367
  - reachability: line 374

  Line numbers are for the embedded script as extracted.
- Optionally also `adb shell -n`.
- In `sync_files.py`, give `run_adb` `stdin=subprocess.DEVNULL` (same class of bug; hygiene).

**How to ship it:**
- It changes an embedded script, so both panel files change, and `EMBEDDED_SCRIPTS` must stay
  byte-identical.
- Add a T2-style test, using the repro's fake adb, to the kit.
- Run the whole port kit.
- Record the new Tk md5 in the port plan's mirror log, and add status lines to both plans.

Effort: small and well-defined (High). The user asked to *investigate*; approval to ship B0 was requested
and **not yet given**. Ask once, then build.

**What it means in the field until it ships:**
- "confirmed fixed" headsets really got SLEEP → WAKE.
- FAILED headsets never received a command. The workaround is the Sleep → Wake button.

**Owned mistake:** the 30 Sep audit read these loops and missed C1. It is recorded as an addendum in the
audit doc.

---

## 5. Audit findings and the fix plan

The details and line numbers are in `docs/cxvr_code_audit_2026-09-30.md`; the designs are in
`docs/cxvr_audit_fix_plan.md`.

**High:**
- **H1: the headtracking lock can be inherited by the adb server** (verified with a real adb).
  - `acquire_lock` holds `massconnect.lock` on fd 9, and bash doesn't set close-on-exec.
  - If an adb call inside the locked region starts the adb server (for example after Kill ADB server), the
    server inherits the lock for its whole life.
  - From then on the watchdog skips every cycle, which quiet mode hides. Manual Connect gives up after 30 s,
    and stale-lock recovery can't trigger because `release_lock` deleted the `.pid` file.
  - Fix B1.1: `9>&-` on the in-lock adb calls at lines 202, 248, 262 and 608; `adb start-server` outside the
    lock; close fd 9 when acquiring fails. Recovery identifies the real holder, breaks a non-massConnect
    holder under a second lock, and checks the inode after locking.
- **H2: the auto-started Headtracking watchdog acts on evidence its own log calls "SUSPICIOUS"**, ignores both
  brakes, and on an empty state folder sleep/wakes every headset.
  - Fix B2.1 (designed at Max): record fixes by **boot_id set**, not per IP; add `tracking_since`.
  - The watchdog fixes automatically only boots after tracking began, subject to the brakes.
  - Show Mode allows only fresh reboots (uptime under 300 s).
  - Manual Connect asks first when Show Mode is on.
  - Migrate the old per-serial files.

**Medium:**

| ID | Finding |
|---|---|
| M1 | Quiet mode hides watchdog failures. Fix: `[attention]` lines are always forwarded. |
| M2 | popupWatchdog has no observe-only mode, no arm step, no brakes, loose detection, and a possible HOME loop. |
| M3 | Probe Case A also matches a headset slept on purpose or taken off. Fix: require `mWakefulness=Awake`. |
| M4 | Overheat: stale logcat evidence repeats BACK; "heat" matches "theater"; act only on window-list evidence. |
| M5 | "Full Keepalive (reconnect+wake)" never reconnects: the panel passes no `--connect-file`. |
| M6 | Reader threads die on invalid UTF-8 or unexpected errors, leaving buttons disabled and processes untracked. |
| M7 | One exception kills the Tk log loop for good; cross-thread dict iteration races can raise one. |
| M8 | Closing the panel kills a running action without asking; a stale `sync_in_progress` is never cleared. |
| M9 | `v3.local` writes: the backup is unchecked, and the file is pushed over the live one. |
| M10 | Volume reads the speaker's level whatever the active output; per-press adb calls run concurrently. |
| M11 | Unthrottled adb bursts: screenRefresh sends about 1,470 commands for 70 headsets. |
| M12 | A corrupt or half-written config resets silently, losing the tested marks. |
| M13 | The prune confirmation and the free-text device list don't name their scope. |

**Low (L1–L31), Qt-only (Q1–Q4) and kit (K1–K4):** see the audit.

**Plan order.** Each batch goes into both files, gets the whole kit, and ships on its own:
1. **B0:** C1 hotfix.
2. **Batch 1** (Extra high): H1; M6–M9; M12; M13; the `sync_files.py` bugs L18–L24; L25; L26; Q1–Q3; K1–K4;
   and port plan §14 items 1–3 (the stale Running row, `timeout` stragglers via a session kill, the Tk mouse
   wheel). Plus test infrastructure T3 (real-adb lock test) and T4 (`sync_files` harness as a file).
3. **Batch 2** (Extra high; designed): the watchdogs. H2 with L1–L4, M1, M2, M3, M4, M5, L27 and L28. Plus T1
   (a Python fleet-simulator fake adb) and T2 (script tests).
4. **Batch 3** (Extra high): `cxvr_fleet.sh`, a new shared embedded helper for throttled fan-out with one result
   line per headset. Also: verified Sleep → Wake (gated `sleepwake.verified_refresh`), the new volume method
   (gated `volume.v2`), the Snapshot and Delete Video improvements.
5. **Batch 4** (High): refresh rate (gated `power.refresh_rate`; a new `displayRate.sh`; `setprop
   debug.oculus.refreshRate 60|72`; Check shows the getprop value and the newest logcat `VrApi FPS=… Temp=…`
   line), and restore normal power settings (gated `power.restore_power`).
6. **Then port Phase 2,** which ports the fixed logic.

**Decisions assumed (A1–A8; the user said "proceed" without objecting; any can be changed):**

| # | Decision |
|---|---|
| A1 | Fixes go into **both** panel files. |
| A2 | Changes that only make a watchdog do less ship in place, not hidden. Only new things are gated. |
| A3 | Popup recovery is observe-only until armed, with a confirmation at each armed start. |
| A4 | Under Show Mode, the Headtracking watchdog still fixes fresh reboots (under 5 min); others wait. |
| A5 | Keepalive really reconnects from `known_ips.txt` (current subnet, throttled). |
| A6 | Stay-Awake, Keepalive and Heartbeat stay exempt from the brakes (they only wake and ping). |
| A7 | Refresh rate is manual only; gated; on the Power page. |
| A8 | Port plan §14 items 1–3 are included. |

**Constraints settled in the chat:**
- The Oculus Go supports only **60 Hz and 72 Hz**, and the app chooses. 30 Hz is impossible and would cause
  judder and sickness; don't propose it.
- Meta documents `debug.oculus.refreshRate` only for the Quest, so it's unverified on the Go.
- **Audio streaming or monitoring of headsets: dropped by the user. Don't pursue.**
- **N1 (unverified).** `sync_files.py`'s Keep screen on sends `prox_close` then `automation_disable`.
  Community docs say the second re-enables the proximity sensor, so the pair likely cancels out. Don't
  change it until one headset has been checked (fix plan §9 step 7).

---

## 6. Field data worth knowing

**From the 3 Oct log:**
- 80 headsets connected, 72 had just booted (uptimes 138–229 s), and 8 were already fixed this boot.
- `known_ips.txt` has 75 entries from other subnets (skipped, as designed).
- **Volume runs:**
  - **.116 never moved** (11, after 10 UP presses over two runs). Possibly headphones or a cable (M10), or
    key events ignored.
  - **Several headsets changed volume with nothing sent to them**, between reads seconds apart: .109, .167,
    .209 and .224 went to 15; .42 to 0; .12 dropped from 12 to 9. Probably viewers pressing the headset
    buttons during a show. Not confirmed; ask the user.

**From earlier sessions** (full detail in the state summary):
- Space held by aborted pushes is released by a reboot.
- The Headjack catalog (`files/App/<id>.v3`) is authoritative; `v3.local` is not. Expect 8/13 videos, by
  design.
- Headset friendly names are not stored on the headset.
- The SD-clone content folder has 15 real files and 29 protected bookkeeping files.

---

## 7. Open questions (waiting on the user)

1. **Ship hotfix B0 now?** This is the most urgent item.
2. Which features are marked tested on the laptop (`tested_features` in the config)?
3. Do headsets ever have headphones plugged in at shows? This sets how urgent M10 / B3.3 is. And what about
   .116?
4. A1–A8 are assumed. Any to change?
5. Port Phase 0 assumptions D1–D5 are still unconfirmed:
   - D1: one file, renamed at cutover
   - D2: the user uploads the files
   - D3: the Screen Capture features before the rehearsal
   - D4: the panel on the left half of the screen (960×1040) during shows
   - D5: the panel opens on Connect
6. The user's double-click check of the Phase 1 Qt panel on the laptop hasn't been reported.
7. **Evidence still to capture** (fix plan §9), each a Diagnostic Snapshot taken through the GUI:
   1. a headset slept on purpose
   2. a headset taken off a head
   3. a headset with headphones plugged in
   4. whether HOME returns to the app
   5. the overheat prompt
   6. any existing snapshot folder, for the current refresh rate and `VrApi` lines
   7. Keep screen on followed by taking the headset off (N1)
8. **Carried from earlier sessions:**
   - taskbar grouping of batch windows (`wmctrl -lx`)
   - the headset friendly-name `settings get` check
   - v4l2loopback setup for Phase 4 double view
   - the multi-AP plan

---

## 8. Lessons and gotchas (each one cost time before)

**Bash and processes:**
- **Never run `adb shell` inside `while read … done < file` without `< /dev/null` or `-n`** (C1).
- **Bash fds aren't close-on-exec.** A forked adb server inherits locks (H1).
- **`timeout` creates its own process group.** killpg misses it, so kill by session.
- **Don't use pkill patterns that match your own command line.** It killed the test shell once.

**Tests and harnesses:**
- **Always stub `kill_process_group` in tests.** A fake pid once signalled the test's own group.
- **The Tk `ControlPanel.__init__` resets the geometry.** Set the size after constructing it.
- **In the kit's thread stub, `_run_command`'s worker is recognized by `_run_command` in its qualname.**
  Keep that if you restructure it.

**Qt:**
- **Signal handlers only run while Python code runs.** Under Qt's idle event loop they don't, so the 100 ms
  pump timer must keep running.
- **QDockWidget layout saving needs object names.**

**Python and text:**
- **`text=True` pipes decode strictly.** Use `errors="replace"`.
- **Python 3.11 only:** no 3.12-only syntax (no reusing the same quote character inside an f-string).

**Workflow:**
- **The cloud workspace reset once.** Keep edits as replayable scripts. On a laptop, use git.

---

## 9. Next steps, in order

1. **Check the files.** Confirm the md5s in §1 against the user's production panel. Set up the environment
   (§3) and run `port_kit/run_all.sh cxvr_control_panel.py cxvr_control_panel_qt.py`; it must be all pass.
   Run `repro/c1_headtracking_stdin/repro_c1.sh cxvr_control_panel.py`; it should show the bug.
2. **Ask the user** to approve B0. Ask open questions 2 and 3 at the same time.
3. **Build B0 in both files** (High effort):
   - Re-embed the script with exact `repr()` replacement, then check embedded vs standalone byte-for-byte.
   - Add a kit test, using the repro's fake adb, that fails on the old script and passes on the new one.
   - Run the whole kit, then hand over both files.
   - Tell the user to check on the fleet: a Full Scan with every headset freshly booted should end with
     close to 100 % confirmed.
4. **Batch 1** (switch to Extra high), following fix plan §4.
5. **Batches 2–4** (fix plan §5–7), then **port Phase 2** (port plan §8).

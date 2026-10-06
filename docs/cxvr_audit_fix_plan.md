# CXVR audit fix plan

Plan v1 · 30 Sep 2026 · written at Max effort.

Companion docs:
- `cxvr_code_audit_2026-09-30.md`: the findings. IDs such as H1 or M6 refer to it.
- `cxvr_pyside6_port_plan.md`: the port. §14 there lists four findings from Phase 1.

The status log is §12.

---

## 1. In brief

**What.** Fix every finding from the 30 Sep audit and the Phase 1 findings in port plan §14, and add
refresh-rate controls.

**Where.** Both panel files.
- The embedded scripts are byte-identical in the two files.
- The Qt panel's logic is a verbatim copy of the Tk panel's.
- So every fix lands in both files, and the port kit keeps proving they behave the same.

**How.** Four batches. Each is built, tested and shipped on its own: the Tk panel, the Qt panel and the
port kit.
- **Batch 1** comes first. It holds the High lock bug and the fixes that stop the panel from getting
  stuck.
- **Batch 2** covers the watchdogs. Their design is in §5, written now at Max effort.
- **Batch 3** covers the commands that go to the whole fleet.
- **Batch 4** adds the new controls.

**When.** Before Phase 2 of the port, so Phase 2 ports the fixed logic.

**Effort (rule 3):**

| Batch | Effort | Chats |
|---|---|---|
| 1 | Extra high | 1–2 |
| 2 | Extra high (design done here) | 1–2 |
| 3 | Extra high | 1 |
| 4 | High | 1 |

**Needed from you:**
- The decisions in §2. The defaults below are assumed until you say otherwise.
- Which features you've marked tested.
- The evidence in §9.

## 2. Decisions (defaults assumed; change any of them)

| # | Decision | Assumed |
|---|---|---|
| A1 | Fixes go into **both** panel files. The Tk panel stays production and gets them as each batch ships. | Yes |
| A2 | Changes that only make a watchdog do *less* ship in place, without hiding the watchdog. Only new things go under Testing: refresh rate, restore power settings, verified Sleep → Wake, and the new volume method. | Yes |
| A3 | Popup recovery starts observe-only and needs arming, with a confirmation, at each armed start (like Overheat). | Yes |
| A4 | Under Show Mode, the Headtracking watchdog still fixes a headset that has just rebooted (up < 5 min). Others wait until Show Mode is off. | Yes |
| A5 | Full Keepalive really reconnects, using massConnect's known-address list (current subnet only). | Yes |
| A6 | Wake pulses (Stay-Awake, Keepalive) and Heartbeat pings stay exempt from the brakes, because they only wake and ping. *New; not asked before.* | Yes |
| A7 | Refresh rate is manual only (no automatic re-apply after a reboot), on the Power page, under Testing. | Yes |
| A8 | Port plan §14 items 1–3 are included: the stale Running row, `timeout` stragglers, and the Tk mouse wheel. | Yes |

**Still open:**
- Which features are marked tested on the laptop.
- Do headsets ever have headphones plugged in at shows? This sets how urgent B3.3 is.

## 3. Ground rules for every batch
- **Both files.** Edit both panel files.
  - `EMBEDDED_SCRIPTS` stays byte-identical in them.
  - Copied methods stay identical after the three substitutions, and `t_integrity.py` checks this.
  - Replace whole methods by AST range; use exact-match edits (count == 1) for small changes.
- **Rule 1.** A new script flag is only ever passed by the panel, or is set from a GUI control. Values
  nobody needs to change are constants inside the script, not flags.
- **Rule 2.** Anything new goes into `GATED_FEATURES` and `_testing_items()`.
- **Tests.**
  - `run_all.sh` passes before and after.
  - Every batch adds the tests listed with it.
  - Python 3.11 for everything; `py_compile`, `pyflakes` and `bash -n` on every file.
- **Shipping.** `cxvr_control_panel.py`, `cxvr_control_panel_qt.py` and the port kit go to
  `/mnt/user-data/outputs/`.
  - Port kit versions: v1.1, v1.2, v1.3 and v1.4 for batches 1–4; Phase 2 is v2.
  - The port plan's mirror log and this plan's status log get one line each.
- **Edits as scripts.** Keep every edit as a replayable script; the workspace can reset.
- **Keep the frozen Tk panel's UI changes small.** Change the logic, dialogs and log text. Rearrange no
  pages.

---

## 3b. Hotfix B0: the headtracking fix skips most headsets (found 3 Oct 2026, ahead of Batch 1)
**Finding C1 (critical, reproduced).** In `apply_headtracking_fix` (massConnect.sh), the detect, SLEEP, WAKE
and reachability loops read the device list with `while read … done < file` and start each headset's
`adb … shell …` in the background. Bash doesn't give those background subshells `/dev/null` as input,
and `adb shell` forwards its input to the headset (that's what `adb shell -n` turns off). So the first
adb client to start reads the rest of the device list. The loop then hits end-of-file and stops after
roughly the first 10–15 headsets.
- The rest never get SLEEP or WAKE. Their result files don't exist, which is the `sleep= wake=` in the
  log.
- Each retry reaches the next batch, so a 72-headset run ends with about 40 fixed and the rest FAILED.
- Sleep All, Wake All and Sleep → Wake loop over a variable (`for d in $devices`), so every headset gets
  the command. That's why they're reliable.

**Evidence:** the user's log of 3 Oct 2026 (72 headsets: 40 confirmed, 32 failed, every failure with an
empty sleep result). Reproduced here with a fake adb that reads its input the way the real client does:
11 of 72 SLEEPs sent over 3 attempts. With the fix: 72 of 72 SLEEPs sent, 432 of 432 WAKEs, all
confirmed.

**Fix.**
- Give each background subshell in those loops `< /dev/null`: the detect loop (lines 247–265), SLEEP
  (345), WAKE (359), reachability (374).
- `sync_files.py`'s `run_adb` gets `stdin=subprocess.DEVNULL` (hygiene; same class of bug).
- Tests: the reproduction, as a T2 case with a stdin-reading fake adb, plus the full port kit.

**Ships alone, before Batch 1**, once approved. Small and well-defined: High effort.

---

## 4. Batch 1: stop the stuck states (Extra high)

### B1.1 The headtracking lock (H1), in massConnect.sh
**Prevent.**
- Add `9>&-` to the four adb calls made while the lock is held (lines 202, 248, 262 and 608).
- Before each watchdog attempt to take the lock, start the server outside it:
  `timeout 10 adb start-server >/dev/null 2>&1 9>&-`.
- `acquire_lock` closes fd 9 when it fails. Today a waiting process keeps the file open, which hides who
  really holds it.

**Recover.**
- A lock is legitimately held only while `massconnect.lock.pid` names a live process whose command line
  contains `massConnect.sh`.
  - Check twice, 1 s apart, to cover the moment between locking and writing the pid.
  - Anything else is stale. Example: an adb server that inherited the lock and has no pid file.
- Breaking a stale lock happens under a second, short lock: `massconnect.lock.break` on fd 8. No adb call
  runs inside it.
  1. Re-check.
  2. Remove and recreate the lock file. That gives it a fresh inode, so the old holder no longer matters.
  3. Lock it.
- After **any** successful lock, the path's inode must match fd 9's. If it doesn't, another process
  replaced the file: drop the lock and try again.
- Log line:
  `[attention] lock was held by <command> (pid N), not by a massConnect run -- broke it`.
  The holder is found by scanning `/proc/*/fd`.

**Tests (T3, real adb).**
- After `adb kill-server`, the next watchdog cycle runs instead of skipping.
- A planted holder (a `sleep` holding the fd, no pid file) is broken.
- A live massConnect holder is respected.
- Two processes breaking at once end with exactly one holder.
- The old script, run against the same setup, still shows the bug. This is the negative control.

### B1.2 Reader threads (M6, L29, and the "nothing running" moment in plan §12)
**`popen_in_own_group`.** When it's called with `text=True` and no encoding, it uses
`encoding="utf-8", errors="replace"`. Every text pipe (one-shot actions, watchdogs, scrcpy) then survives
an invalid byte.

**`_run_command`.**
- Start the process on the main thread, as `_start_toggle` already does. `current_proc` is then set before
  the method returns. That closes the "nothing running" moment and the double-start race.
- The reader thread (still named `worker`, so the kit's thread stub still recognizes it):
  1. Reads the output and waits for the process.
  2. In `finally`: clears `current_proc` only if it is still this process, removes the sync sentinel, and
     posts "done" **last**.
- An unexpected error is logged. The process group is killed, so nothing runs untracked, and "done" is
  still posted.
- An `OSError` at start (a permission error, for example) is logged, the buttons come back, and the
  sentinel is removed.

**The `_start_toggle` reader.** Gets the same safety net: log the error, then mark the toggle ended.

### B1.3 The log loop (M7, L30, L11, Q2)
**Tk `_poll_log_queue`:**
- Each item is handled in its own try/except. An error goes into the log as
  "[panel error -- please report this]" with its traceback.
- The reschedule moves into `finally`.
- At most 2,000 items per tick (as in Qt). When more are waiting, the next tick comes after 10 ms.
- Runs of plain lines go into the log in one insert.
- The Tk log keeps the last 20,000 lines, like Qt.

**Qt pump.** Per-item try/except as well.

**Both panels:**
- New output scrolls the log only when it was already at the bottom, so reading earlier lines isn't
  interrupted.
- Log colours check negative phrases first: NOT CONFIRMED, not confirmed, UNREACHABLE, FAIL and WARNING
  show red. Only then do "confirmed" and "connect phase finished" show green.

**Dictionaries other threads change.** Iterate over a snapshot (`list(...)`) in:
- `_screencap_status_text`
- the batch-slot loop
- `action_batch_preview_toggle`
- the count in Kill ADB server

Then grep for any other loop over `scrcpy_procs`, `batch_scrcpy_procs` or `toggle_procs`.

### B1.4 The stale "Running" row (port plan §14.1)
`_refresh_toggle_state` compares every switch with `toggle_procs` on every tick. The background-task
label still updates only when something changed.

### B1.5 Stopping cleanly (§14.2, L8)
**`kill_process_group`:**
- Signal `proc.pid` as the group directly. Every child starts its own session, so the pid is the group id,
  and this works even after the leader has been reaped.
- A forced kill also sends SIGKILL to every process in that session. That reaches `timeout` and its adb.

**Graceful Stop.** SIGINT first. A background helper then waits 3 s and kills whatever is left of the
session.

**Never signal the panel's own session.**

**Daemon exits.** overheatWatchdog.py and blackScreenProbe.py catch KeyboardInterrupt, log "stopped" and
exit cleanly, so a Stop no longer prints a traceback into the log.

**Lifecycle test.** Its expectation changes from "11 stragglers, gone after 20 s" to "nothing left after
1 s".

### B1.6 The Tk mouse wheel (§14.3)
Replace the class bindings for TCombobox wheel events (`<MouseWheel>`, `<Button-4>`, `<Button-5>`) with a
no-op that passes the event on. The selected value never changes, and the page still scrolls. Verify
under Xvfb with the existing wheel check, which is reversed.

### B1.7 Closing the panel and the sync brake (M8)
**Closing.** If a one-shot action is running, closing the window asks first (default No):

> "<script> is still running (started 14:02). Closing stops it at once; headsets in the middle of a
> sleep → wake may be left asleep. Close anyway?"

- Tk: in `_on_close`. Qt: in `closeEvent`, which ignores the close event on No.
- SIGTERM, SIGINT, SIGHUP and atexit still clean up without asking.

**The sync brake.**
- When the running action was a sync, cleanup removes `sync_in_progress` itself.
- At startup, a leftover `sync_in_progress` is removed if no `sync_files.py` process is running (other
  than `--keepalive`), and the log says so.
  - If one *is* running (a sync orphaned by a crashed panel), the file stays and the log names that
    process.
- The log says when the sync brake goes on and off: "automated recovery paused for the sync" and
  "…resumed". This works in both panels with no layout change.

### B1.8 Config (M12)
- `save_config` writes a temporary file, fsyncs it, then `os.replace`s it over the config.
- `load_config` handles a file that isn't valid JSON, or isn't a JSON object:
  - It renames the file to `config.json.corrupt-<time>` and loads the defaults.
  - The panel shows a warning at startup that names the kept file and says the tested marks need
    re-marking.
  - It never silently overwrites the file.

### B1.9 Sync scope (M13, L17)
**Prune.** The confirmation names:
- the scope ("all 68 connected headsets", or the serials)
- the remote folder

It suggests a Dry Run first, and defaults to No.

**Advanced › devices.**
- Before a run, entries that aren't connected are listed: "These aren't connected: … Sync the rest?"
  (default No).
- `sync_files.py` also logs allow-listed serials it didn't find, and exits 1.

**Delete Video.**
- Use `ALL_DEVICES_LABEL` instead of the literal.
- For ALL, the confirmation gives the number of connected headsets.

**Qt Phase 2.** The free-text device box becomes a multi-select device picker. It goes in §6 of the port
plan as an intentional difference then.

### B1.10 Safe v3.local writes (M9)
One function, `safe_write_v3local`, in sync_files.py. Its two writers and delete_video.py use it:
1. Back up, and check the backup worked.
2. Push to `v3.local.cxvr_new`.
3. Check the size and md5 on the headset.
4. `mv` it over `v3.local`.
5. On any failure, remove the temporary file and leave `v3.local` untouched.

If the backup fails, nothing changes. Keep the newest 5 backups. The race with the app itself stays
unverified (§8).

### B1.11 sync_files.py bugs (L18–L24)
- **`run_adb`.** Decode with `errors="replace"`. An `OSError` returns a failed result ("adb couldn't be
  started: …") instead of raising.
- **`batched_size_check`.** Split at the *last* colon. A malformed line is logged and skipped, never
  fatal.
- **`.bak` protection.** Only names ending in `.bak`, `.bakN` or `.bak.<timestamp>`.
- **`push_one`.** Re-check free space before a retry, and stop retrying when the file no longer fits.
- **Exit code.** 1 when any headset's scan failed. CRASHED is followed by the traceback in the log file.
- **`Log`.** One write per line, under a lock, so lines don't merge.

### B1.12 Scripts on disk (L25, plan §12)
`materialize_scripts` rewrites a script only when its content changed. It writes a temporary file, then
`os.replace`, and keeps the executable bit.

### B1.13 Freezes (L26)
**Kill ADB server** runs on a worker thread.
- Its result goes to the log through a new queue message.
- The failure dialog is shown from the pump.

**Stopping batch preview.**
- It signals the stop and closes the windows at once.
- It joins the slot threads in the background.
- Windows a slot opens after that are still closed by the existing check made under the launch lock.

**Device-list refreshes.** These keep their 10 s limit: they're explicit and rare (§8).

### B1.14 Errors and a style fix (Q1, Q3)
- **Both panels.** `threading.excepthook` sends errors from worker threads into the live log.
- **Tk.** `report_callback_exception` does the same for errors in Tk callbacks.
- **Qt.** The sidebar buttons get their own focus style.

### B1.15 Port kit (K1–K4) and new tests
- **K1.** A check that every attribute the copied logic guards with `hasattr`/`getattr` is set in the Qt
  panel. A per-phase allowlist names the pages still to come.
- **K2.** The navigation rule only allows the expected Qt landing page. An empty recording fails.
- **K3.** In `run_all.sh`:
  - each step runs in its own subshell
  - a usage message
  - `PY311` for `compare.py` and the rollback test
  - pyflakes also on `tk_tests/`
- **K4.** `record.py` refuses to run unless HOME points at a temporary folder.
- **New tests:** T3 and T4 (§10).

**Check on real headsets after Batch 1:**
1. Kill ADB server, wait two minutes, then confirm the log shows normal watchdog cycles and Connect still
   applies the fix.
2. Start a Connect, try to close the panel, and say No.
3. A sync Dry Run with prune ticked: check the dialog's scope.
4. Close the panel and run the §9 step 11 `ps` check from the port plan: nothing may be left, with no
   wait needed.

---

## 5. Batch 2: watchdogs that act on headsets (designed here; build at Extra high)

### B2.1 The Headtracking watchdog (H2, L1–L4), in massConnect.sh and the Connect actions

**Record fixes by boot, not by address.**
- New state:
  - `~/.cxvr_headtracking_fix/fixed_boot_ids`: one boot_id per line, keeping the newest 2,000.
  - `tracking_since`: epoch seconds.
- A headset counts as fixed when its *current* boot_id is in the set, whatever address it has now.
  - This removes both cases the old code lumped together as "SUSPICIOUS": another headset now answering
    on an address (DHCP churn), and a headset that rebooted while nothing was watching.
  - So "SUSPICIOUS" disappears as a concept.
- **Migration.** On the first run, the boot_ids in the old per-address files go into the set.
  `tracking_since` becomes the oldest of those files' times.
  - The per-address files keep being written, so rolling back to an older panel file still works.
- **No records at all** (a new laptop or account): `tracking_since` is now.

**Who gets fixed.**
A headset's boot time is now minus `/proc/uptime`. The uptime is now read for every headset that might
need the fix.

| Headset | Manual Connect | Watchdog |
|---|---|---|
| boot_id in the set | no | no |
| not in the set, booted after `tracking_since` | yes | yes, if the brakes allow (below) |
| not in the set, booted before `tracking_since`, or uptime unreadable | yes | **no**: one `[attention]` line per boot, "no record of a fix for its current boot -- run Connect to fix it" |

**Brakes on the watchdog (A4):**
- With `sync_in_progress` present, it fixes nothing. One `[attention]` line per boot names the waiting
  headsets.
- With `show_mode` present, it fixes only headsets up for less than 300 s (a fresh reboot can't be
  mid-film). The rest wait with one `[attention]` line per boot. They're fixed in the first cycle after
  Show Mode ends.

**Manual Connect, Full Scan and Purge** still fix every headset without a record; that's an operator
action. When Show Mode is on, the panel asks first:

> "Show Mode is on. Connect also applies the headtracking fix (a quick sleep → wake) to any headset that
> hasn't had it since it last started, which blanks it for a moment. Continue?"

The default is No.

**Checking the sleep (L1).**
- Between SLEEP and WAKE, read `dumpsys power | grep mWakefulness` once per headset, in parallel.
- Log what it shows ("reached Asleep", "still Awake" or "unknown") in the batch log and on the confirmed
  line.
- The confirmation rule stays as it is until the logs show what a working fix looks like; then tighten it.
- Cost: about one adb round trip more of black screen.

**Retries (L2).** Rebuild the transport map before attempts 2 and 3.

**Housekeeping (L3, L4):**
- Correct the process-group comment.
- An EXIT trap removes the temporary files.
- `batch_fix_*.log` files older than 30 days are deleted.

**Summary block.** The lines the panel parses don't change. Two lines are added: "Waiting (Show Mode /
sync): N" and "Not fixed automatically (booted before tracking): N".

**Not covered.** A headset fixed by hand with Sleep → Wake isn't recorded, so the watchdog may fix it
once more. That's the same as today.

### B2.2 The quiet mode shows what matters (M1)
- massConnect.sh starts every line the operator must see with `[attention]`:
  - the failure header and each failed headset
  - waiting and not-fixed notices
  - "the watchdog has skipped 3 cycles in a row (lock held by …)", then every 10 skipped cycles
  - a broken stale lock
- In quiet mode, the panel forwards lines that start with `[attention]`. Verbose is unchanged.
- Each notice appears once per headset per boot, not every cycle.

### B2.3 Popup recovery (M2)
**popupWatchdog.sh:**
- Flags: `--arm` (observe-only without it) and `--state-dir` (the panel passes its config folder, for the
  brakes).
- Constants, not flags: 2 mismatches in a row before acting, and at most 2 HOME presses per mismatch
  streak.

**Detection.**
- Read the focus lines with the grep running on the headset.
- The mismatch rule is unchanged: neither line names the app.
- When the two lines disagree, log both. That's evidence for the detection question in the audit.

**Before sending HOME, all of these must hold:**
- 2 mismatches in a row
- the headset is awake (`mWakefulness=Awake`, read only at that point)
- both brakes clear
- armed
- fewer than 2 presses already in this streak

After 2 presses: "[attention] giving up on <d>: still not back in the app after 2 HOME presses". It isn't
touched again until the app has been seen in front.

**Observe-only** logs "would send HOME" once per streak.

**Panel.**
- The Popup row gets the mode pill and an "Arm (send HOME)" checkbox, saved as `popup_arm`.
- An armed start asks first and quotes the rule: 2 checks in a row, at most 2 presses, paused by Show Mode
  and syncs, and HOME also leaves Oculus Home or the system menu.
- Tk now; Qt in Phase 2, with the Sleep / Wake page.

### B2.4 Black-Screen Probe (M3); gated, stays observe-only by default
- It acts only when wakefulness is exactly `Awake`.
  - `Asleep` or `Dozing` → verdict `display_off_asleep`: logged, never actionable.
  - Missing → `unknown_wakefulness`.
- New CSV column `proximity`, from `mProximityPositive=` if this build prints it (unverified). It's
  evidence for telling "taken off" apart from the fault.
- The arm dialog is corrected: asleep headsets are never touched, and a headset just taken off may still
  match, so check the probe's data before arming.

### B2.5 Overheat Dismissal (M4); gated, stays observe-only by default
- **It acts only on window-list evidence**, meaning a prompt that is visible now and re-read every cycle.
  So old log lines can no longer trigger it.
  - Logcat matches are observations only.
  - The first cycle records existing matching lines as a baseline. After that, each new line is logged
    once.
- The package filter applies to logcat lines too.
- **Default pattern.** Word boundaries:
  `\b(?:thermal|overheat\w*|too hot|temperature|cooling|heat)\b`, so "theater" no longer matches. A saved
  pattern equal to the old default is migrated, with a log line.
- **Speed.** Headsets are checked in parallel, 8 at a time.
- **Arm dialog.** Says it acts only on a visible prompt. If the prompt turns out not to be in the window
  list, the armed watchdog never acts, and the evidence (§9) tells us that.

### B2.6 Full Keepalive (M5)
- **sync_files.py.** New flag `--connect-subnet PREFIX`.
- **Panel.** It passes `--connect-file ~/.cxvr_massconnect/known_ips.txt` and
  `--connect-subnet <CXVR_SUBNET_PREFIX>`.
- **Reconnects.** Only addresses that aren't already connected, 20 at a time, 5 s each.
- **Wake pulses.** In parallel, 20 at a time.
- **Errors.** Each cycle's work runs inside try/except; an error is logged and the loop goes on.

### B2.7 Panel safety notes (L27, L28)
- **Other-instance warning.** It uses one list of the panel's background scripts, now including the
  three that act on headsets.
- **Sleep confirmation.** Adds a line when Stay-Awake, Keepalive or an armed probe would wake the headsets
  again.
- **Show Mode.** The Connect confirmation from B2.1.

**New tests:** T1 and T2 (§10).

**Check on real headsets after Batch 2:**
1. Show Mode on: reboot one headset; it gets the fix within about a minute.
2. Show Mode on: a headset whose fix record you've removed is reported, not touched.
3. Popup recovery, observe-only, with the app closed on one headset: the log says "would send HOME".
4. Armed: one HOME, then at most one more, then "giving up".
5. Full Keepalive: disconnect one headset's adb, wait for a cycle, and confirm it reconnects.

---

## 6. Batch 3: commands to the whole fleet (Extra high)

### B3.1 Shared helpers, `cxvr_fleet.sh` (M11, L5–L7)
`cxvr_fleet.sh` is a new embedded file that the fleet scripts source. There are now 16 embedded files;
Batch 4 makes it 17.
- `cxvr_ready_devices`: `adb devices` with a 10 s limit. If adb doesn't answer, the script says so and
  exits 1.
- `cxvr_each MAX FUNC DEVICE…`: runs FUNC for each headset, at most MAX at once (`wait -n`).
  - One result line per headset, then "N ok, M failed".
  - Returns 1 if any failed.
- Default limit: 20, the value massConnect already uses.

**Scripts that use it:**
- **sleepAll, wakeAll, powerOff, rebootAll.** One command per headset, a line each, exit 1 on any failure.
- **stayAwake.** Each pass waits for itself. The next pass starts 5 s after the last one began, or at once
  if it took longer.
- **heartbeat.** Pings 0.5 s apart as now, with a 10 s minimum per pass, and "not responding" lines.
- **screenRefresh.** Gets its final `wait` (L7). The 16-sleep burst stays until B3.2 is marked tested.

### B3.2 Verified Sleep → Wake (gated `sleepwake.verified_refresh`, in Testing › Sleep / Wake)
`screenRefresh.sh --verified` handles 20 headsets at a time. For each headset:
1. Send SLEEP.
2. Read `mWakefulness` every 0.3 s for up to 3 s.
3. If it never left `Awake`, send one more SLEEP.
4. Then WAKE, until it reads `Awake` (up to 3 tries).
5. Print a result line: "slept 0.6 s, awake again", "never reached Asleep, woke it anyway", or
   "unreachable".

Once marked tested, it becomes the Sleep → Wake button and the burst is retired.

### B3.3 Volume (M10, L10, L12)
**Today's method, ungated fixes:**
- The first report and the summary read every headset in parallel, printed in headset order.
- Exit 1 when any headset isn't confirmed.
- The colours are fixed in B1.3.

**New method (gated `volume.v2`, in a new Testing › Volume page with the presets and Set level):**
- It reads the level of the output actually in use.
  - The stream's `Devices:` line is matched by name against `Current:`.
  - If the build doesn't print `Devices:`, it falls back to today's reading, labelled "assumed speaker".
- One adb call per headset per round, carrying all of that headset's presses (`input keyevent 25 25 25`).
- Headsets in parallel, 20 at a time.
- Once marked tested, it replaces the old method.

### B3.4 Diagnostic Snapshot (L13–L15) and Delete Video (L16)
**Snapshot:**
- The folder name includes the process id, so two captures can't collide.
- The header no longer says "read-only": the screenshot fallback writes a temporary file and deletes it.
- Headsets are captured 8 at a time.

**Delete Video.** Headsets are handled in parallel, 6 at a time.

**Check on real headsets after Batch 3:**
1. Sleep and Wake on all: one line per headset, and failures named.
2. Volume Check: fast, in headset order.
3. Testing › Volume on one headset: set 8 with the speaker; repeat with headphones if you use them.
4. Testing › Sleep → Wake (verified) on one headset.

---

## 7. Batch 4: new controls (High)

### B4.1 Display refresh rate (gated `power.refresh_rate`)
It sits in Testing › Power until marked tested, then on the Power page.

**New embedded script `displayRate.sh`.** Usage: `--check` or `--set 60|72`, with an optional serial. It
uses `cxvr_fleet.sh`.
- **Set:** `setprop debug.oculus.refreshRate N`, read back with getprop. Each headset reports either
  "override now 60 (a reboot clears it; the app may need restarting)" or FAILED.
- **Check:** for each headset, the override value (or "not set"), plus the newest VR-runtime line from
  logcat (`VrApi … FPS=… Temp=…`) with its time. That shows the rate actually running and the
  temperature.

**Controls:**
- Uses the Power page's headset dropdown.
- Buttons: 60 Hz, 72 Hz, Check current.
- The confirmation names the scope, and mentions Show Mode when it's on.
- A "Last requested" note, as on the Volume page.

**Unverified on the Go:** whether this firmware applies the property, and when. Meta documents it for the
Quest only.
- First test: one headset, set 60, restart the app, then Check.
- To compare heat: the probe's CSV records battery temperature, and Check shows the runtime's `Temp=`.

### B4.2 Restore normal power settings (gated `power.restore_power`; L22)
**`sync_files.py --restore-power`.** For the target headsets it:
- runs `svc power stayon false`
- sets `screen_off_timeout` back to the value saved the first time Keep screen on changed it. That value
  is saved per headset in the state folder. If none was saved, the timeout is left alone and the log says
  so.
- sends `automation_disable`. Per community docs, that hands the proximity sensor back to automatic.

**Panel.** A button on the Power page (Testing › Power until tested). The Keep screen on caption says what
it really does.

**N1 (found while planning).** Keep screen on sends `prox_close` and then `automation_disable`. Per the
same docs, the second undoes the first, so the pair probably cancels out.
- The script's own docstring says their effect was never confirmed.
- Not changed until it's checked on one headset (§9).

---

## 8. Not fixed, and why

| Item | Why |
|---|---|
| L9 (PID reuse in parent checks) | Most current Linux systems hand out PIDs up to about 4 million before wrapping. A daemon would have to outlive the panel *and* find that exact PID reused within minutes. Not worth the change. |
| Q4 (Collapsible untested) | Covered in Phase 2, when a page first uses it. |
| v3.local vs the running app (race) | It can't be locked against from outside the app. The safe write (B1.10) narrows the window to a rename. Revisit with evidence. |
| The `Devices:` line (M10 part 1) | Only in the gated new method (B3.3) until it's tested. |
| N1 (proximity broadcasts) | Waits for the one-headset check (§9). |
| The screen-refresh burst | Stays until the verified version (B3.2) is marked tested. |
| Device-list refresh can freeze for up to 10 s | Explicit, rare, and bounded. |

## 9. Evidence to capture (all through the GUI)
Use Diagnostic Snapshot (from Testing › Snapshot if it isn't marked tested yet) on one headset per step:

| # | Do this | Unblocks |
|---|---|---|
| 1 | Sleep one headset with the Sleep button, wait 10 s, take a snapshot | B2.4, B3.2 |
| 2 | During playback, take a headset off a head, wait 20 s, take a snapshot | B2.4 |
| 3 | Plug headphones in, run Volume › Check, take a snapshot | B3.3 |
| 4 | With Oculus Home in front on one headset, middle-click its Screen Capture window (that sends HOME). Does the app come back? | B2.3 |
| 5 | When the overheat prompt next appears: snapshot with Repeat 3 | B2.5 |
| 6 | Upload any snapshot folder you already have (zipped). Its `getprop.txt` and `logcat_tail.txt` may already show the current refresh rate and the `VrApi` line | B4.1 |
| 7 | Sync one headset with Keep screen on ticked, take it off a head. Is the display still on after 30 s? | N1, B4.2 |

## 10. Test infrastructure added
- **T1, fleet simulator (`kit/fakeadb/`).** A Python program installed on PATH as `adb`.
  - A JSON file describes the fleet, per headset:
    - serial and transport id
    - boot_id and uptime
    - wakefulness
    - volume per output, and which output is active
    - focus lines
    - logcat lines
    - properties
    - reachable, slow, or dropping key events
  - It answers the commands the scripts use, and logs every call with its time.
- **T2, `t_scripts.py`.** Runs each embedded script, taken from the panel file under test, against T1. It
  checks:
  - per-headset lines and exit codes
  - the concurrency limit, measured from the call log
  - the brakes, and observe-only vs armed
  - the Headtracking decision table, including migration
  - popup streaks and giving up
  - the overheat baseline
  - probe verdicts
  - the new volume method with headphones
  - refresh set and check
- **T3, `t_lock_realadb.sh`.** The B1.1 cases, with the real adb binary.
- **T4, `sync_tests/t_sync.py`.** The monkeypatch harness from the state summary, kept as a file. It
  covers:
  - decoding and colon names
  - the `.bak` rule
  - retries with space checks
  - exit codes
  - `Log`
  - each failure point of `safe_write_v3local`
  - Delete Video in parallel
  - keepalive's subnet filter
- **T5, panel tests.** Differential scenarios, Tk click-through checks and Qt behaviour checks for every
  dialog and control that changes. The lifecycle test now expects nothing left behind.
- **T6, integrity.** The new embedded files, `logic_map` updates, and the K1 check.
- **T7.** `run_all.sh` runs all of the above.

## 11. Effect on the port
- **Non-goal exception.** The batches come before Phase 2. The port plan's non-goal ("no changes to
  embedded scripts, safety behaviour or detection logic") still holds for the port phases. These batches
  are the exception, made at your request.
- **Pages already in Qt** (Connect, Volume, Power, Testing › Power, and the strip) get each change in both
  panels in the same batch.
- **Pages still to come** (Sleep / Wake, Content Sync, Delete Video, Testing › Sleep / Wake) get it in Tk
  now and in Qt in Phase 2. The copied logic and the differential suite keep the two in step.
- **No new intentional differences** (port plan §6) are expected. The scrolling change applies to both
  panels.
- **The frozen file's md5 changes** with every batch. The port plan's mirror log records each new value,
  so the start-of-chat check stays meaningful.

## 12. Status log

| Date | Step | Result |
|---|---|---|
| 30 Sep 2026 | Plan | Written at Max effort. Defaults A1–A8 assumed. Waiting on the tested marks and the headphones question. Next: Batch 1 at Extra high. |
| 3 Oct 2026 | C1 found | From the user's show log: the headtracking fix loops lose the device list to `adb shell`'s input (§3b). Reproduced and the fix proven on a fake adb. Hotfix B0 proposed, waiting for approval. |

# CXVR code audit — 30 Sep 2026

## Scope and method

| What | Size | Identity |
|---|---|---|
| Tkinter panel `cxvr_control_panel.py` (frozen, production) | 3,869 lines | md5 `fab82203…6c1` |
| Its 15 embedded scripts (identical in both panels) | 4,204 lines | extracted with `ast.literal_eval` |
| Qt panel `cxvr_control_panel_qt.py` (Phase 1) | 4,337 lines | md5 `da5b0002…e57` |
| Port kit v1 | harnesses, stubs, recorder, comparer, tests, `run_all.sh` | `cxvr_port_kit_v1.zip` |

- Every file was read in full. No test suite was run (as asked), and no file was changed.
- One finding (H1) was reproduced during the audit with a real adb server. The §14 items in the port
  plan were verified in Phase 1. Everything else comes from reading the code and is marked
  **reading**. Items that also depend on how the headsets behave are marked **unverified on the Go**.
- The Qt panel copies the Tk panel's logic verbatim, and `EMBEDDED_SCRIPTS` is byte-identical in both
  files. So, unless a finding says otherwise, it applies to both panels. Line numbers are from the Tk
  file and from the scripts as extracted.

**Severity**
- **High**: can silently disable a core show function, or make headsets act on bad evidence, under
  realistic conditions.
- **Medium**: a real bug or a gap against the project's safety principles, but less likely, or limited in
  impact, or only reachable after a gated feature is armed. Also any significant performance problem.
- **Low**: edge cases, hygiene, cosmetics.

**Rules that apply to every fix**
- The Tk panel is frozen. A fix to it needs your approval, must be mirrored into the Qt file, and gets
  logged in the plan.
- A change to an embedded script changes both files, and they must stay byte-identical.
- Anything that materially changes how headsets are treated goes under Testing until you mark it
  tested.

---

## At a glance

| ID | Sev. | Where | Finding | Basis |
|---|---|---|---|---|
| H1 | High | massConnect.sh | The adb server can inherit the fix lock; the headtracking fix then stops silently | **verified** |
| H2 | High | massConnect.sh `--watchdog` | The auto-started watchdog sleeps and wakes headsets on "SUSPICIOUS" evidence, ignores both brakes, and fixes every headset when its state folder is new | reading |
| M1 | Med | panel `_start_toggle` | Silent mode hides the watchdog's failures, skipped cycles and suspicious reboots | reading |
| M2 | Med | popupWatchdog.sh | Sends HOME on its own: no observe-only mode, no arm step, no brakes, loose detection | reading |
| M3 | Med | blackScreenProbe.py (gated) | "Display off while the app is in front" also matches a headset slept on purpose or taken off | reading, unverified on the Go |
| M4 | Med | overheatWatchdog.py (gated) | Re-reads the same old logcat lines every cycle, so one stale line can trigger BACK over and over; the pattern is too broad | reading |
| M5 | Med | panel + sync_files.py | "Full Keepalive (reconnect+wake)" never reconnects | reading |
| M6 | Med | panel `_run_command`, `_start_toggle` | Unexpected errors kill the reader thread and leave the panel stuck | reading |
| M7 | Med | Tk `_poll_log_queue` | One exception stops the Tk log loop for good; a cross-thread dictionary race can raise one | reading |
| M8 | Med | panel close / sync sentinel | Closing the panel kills a running action without asking; a stale `sync_in_progress` is never cleared | reading |
| M9 | Med | v3.local writers | The backup's result is never checked, and the new file is pushed straight over the live one | reading, unverified on the Go |
| M10 | Med | volumeNormalize.sh | Reads the speaker's level whatever the output; presses to one headset run concurrently | reading, unverified on the Go |
| M11 | Med | fleet-wide scripts | Unthrottled adb bursts (screen refresh: ~1,470 commands for 70 headsets) | reading |
| M12 | Med | panel config | A corrupt or half-written config resets silently and takes the tested marks with it | reading |
| M13 | Med | Content Sync | The prune confirmation doesn't name its scope; the free-text device list drops unknown names silently | reading |
| L1–L31 | Low | various | see below | reading |
| Q1–Q4 | Low | Qt panel only | see below | reading |
| K1–K4 | Low | port kit | see below | reading |

---

## High

### H1. The headtracking-fix lock can get stuck, and the fix then stops without any visible sign — verified
**Where:** massConnect.sh, `acquire_lock` / `release_lock` (122–150). The adb calls below run while the
lock is held on fd 9:
- `watchdog_cycle`: `timeout 10 adb devices` (608)
- `build_transport_map` (202)
- the boot_id and uptime reads (248, 262)

The fix subshells already close fd 9 (345, 360, 374).

**What happens:**
1. `exec 9> "$LOCK_FILE"` opens the lock on fd 9. Bash doesn't mark it close-on-exec, so every child
   inherits it.
2. Sometimes the adb server isn't running when one of the calls above runs: right after **Kill ADB
   server**, or after the server crashed. adb then forks a new server, and that server inherits fd 9,
   and with it the lock.
3. The server keeps the lock for as long as it lives.

**Impact:**
- Every watchdog cycle logs "a manual massConnect.sh operation is in progress -- skipping this
  cycle". The panel's silent mode hides that line (M1).
- A manual Connect waits 30 s, then prints "Could not get exclusive access… skipping the fix". It
  points at a `.pid` file that `release_lock` has already deleted.
- Stale-lock recovery can't start, because it needs that `.pid` file.
- Rebooted headsets never get the headtracking fix until the adb server is killed again. If the
  watchdog is the first thing to call adb after that, the lock gets stuck again.

**Evidence:** reproduced here with a real adb.
- The forked server (`adb -L tcp:5037 fork-server server --reply-fd 4`) held `massconnect.lock`.
- The next cycle found the lock held.
- `adb kill-server` freed it.
- The panel's pipes are not affected: the server's output goes to `/tmp/adb.*.log`.

**Fix** (embedded script, so both panel files change):
- Close fd 9 on every adb call inside the locked region (`9>&-`, as the fix subshells already do), or
  run `timeout 10 adb start-server 9>&-` before taking the lock.
- Make recovery robust: when `flock -n` fails, identify the process that actually holds the lock (for
  example through `/proc/locks`). If it isn't a massConnect.sh process, recreate the lock file, which
  gives it a fresh inode, the same way the existing stale path does.

### H2. The Headtracking Watchdog acts on evidence its own log calls unreliable, and ignores both brakes — reading
**Where:**
- massConnect.sh: detection (244–317), then sleep and wake (340–369).
- The panel starts the watchdog automatically at launch (573); its toggle is at 2440.

**What:**
- **It acts on ambiguous evidence.** A boot_id change on a headset that has been up for more than 300 s
  is logged as "SUSPICIOUS, likely not a real reboot" (297). The headset still goes on the fix list (317)
  and gets SLEEP → WAKE, possibly mid-film.
- **A new state folder means every headset gets the fix.** The folder is `~/.cxvr_headtracking_fix/`. On
  a different laptop, a new user account, or after the folder is cleared, no headset has a recorded boot
  and uptime isn't read. Every connected headset "needs the fix" in the first cycle, including any that
  are mid-film.
- **It ignores both brakes.** It never reads `show_mode` or `sync_in_progress`, and it has no
  observe-only mode and no arm step. The plan (§9 step 5, §14.4) documents this scope, but it goes
  against the safety principles for anything that acts on its own.

**Impact:** a headset can blank and re-wake in front of a viewer during a show.

**Fix (needs your decision):**
- Never act on a SUSPICIOUS change. Log it and skip it.
- On an empty state folder, record the current boot_ids as a baseline, or act only on headsets with low
  uptime.
- Decide what the watchdog may do under Show Mode. A headset that has genuinely just rebooted (low
  uptime) isn't mid-film, so fixing it is arguably still wanted. Anything else should wait for the
  brakes to clear.
- These are behaviour changes to a core daemon, so under rule 2 they need a Testing path. They are
  also safety-critical detection logic (rule 3).

---

## Medium

### M1. Silent mode hides the watchdog's failures — reading
**Where:** panel `_start_toggle`, reader (2281–2297). Silent is the default; Verbose turns it off.

**What:** Only the SUMMARY block reaches the status strip. These lines never reach the log:
- "HEADTRACKING FIX FAILED … on: <names>"
- "[x] NOT confirmed on attempt n"
- "SUSPICIOUS"
- "could not resolve transport id"
- "skipping this cycle"

The strip shows the failed count, but not which headsets failed. A skipped cycle produces no summary, so
the numbers silently go stale. That's how H1 stays invisible.

**Fix:**
- In silent mode, still forward lines that match a short allowlist of failure phrases.
- Show "last watchdog cycle: HH:MM" in the strip, so a stalled watchdog is visible.

### M2. Popup / Crash Recovery sends HOME on its own, with no safeguards — reading
**Where:** popupWatchdog.sh; the panel toggle is at 2451.

**What:**
- **No safeguards.** It sends HOME to any headset whose focus lines don't mention the app (75–93), at
  most once every 30 s per headset, for as long as it runs. It has no observe-only mode and no arm step,
  and it doesn't check `show_mode` or `sync_in_progress`.
- **Its detection is loose both ways.**
  - It passes if *either* the mCurrentFocus line *or* the mFocusedApp line names the app (66–76). A
    dialog in front of the app probably leaves mFocusedApp naming the app, so the case it exists for may
    never trigger. The script's own header says this is unverified.
  - It fires on normal states where the app isn't in front: Oculus Home between shows, the system menu,
    and app start-up.
- **HOME may not bring the app back.** If HOME goes to Oculus Home (that is, the app isn't the headset's
  launcher), the app is still not in front, and the script presses HOME again every 30 s without ever
  restoring it. Unverified: this depends on whether the app is set as the launcher.
- **It is heavy on the WiFi.** Every 10 s it pulls the full `dumpsys window windows` from every headset
  in parallel, over the AP the films stream through.

**Fix:**
- Observe-only by default, plus an arm confirmation that quotes the rule.
- Honor both brakes.
- Base the detection on Diagnostic Snapshot evidence.
- Grep on the headset (`adb shell "dumpsys window windows | grep -E '…'"`).
- Check the outcome after HOME, and stop after a few failures.

### M3. Black-Screen Probe: "display off while the app is in front" also matches a headset slept on purpose or taken off — reading, unverified on the Go
**Where:** blackScreenProbe.py `classify()` (143–171); the arm dialog in the panel (2523–2531). The
feature is gated and observe-only by default.

**What:**
- `classify()` uses only the display state and the foreground app. After **Sleep**, or when a headset is
  taken off and its proximity sensor blanks the display, the app likely stays the focused app. The
  sample then reads `display_off_during_app`.
- If armed while Show Mode is off (between shows, for example), the probe would wake those headsets after
  3 samples (about 60 s), and again every 120 s.
- It already records `mWakefulness` and audio activity, but ignores both. The arm dialog says the case
  "can't be confused", which is true for film transitions but not for a deliberate sleep.

**Fix:**
- Don't act when wakefulness is Asleep or Dozing.
- Require evidence of playback, such as audio playing.
- Capture evidence first with the Diagnostic Snapshot: one headset slept deliberately, one taken off a
  head.
- Correct the dialog text.

### M4. Overheat Dismissal: one stale line can trigger BACK over and over — reading
**Where:** overheatWatchdog.py (92, 117–123, 156–173). The feature is gated and observe-only by default.

**What:**
- **Stale evidence.** `logcat -d -t 200` re-reads the last 200 lines every cycle. A matching line stays
  in that window until 200 newer lines push it out. Armed, the watchdog would send BACK every cooldown
  (60 s) because of the same old line, and BACK inside the app may exit playback.
- **The pattern is too broad.** `heat` matches "theater", and `temperature` matches routine battery
  logs.
- **Its own lines aren't excluded.** The docstring (101–103) and the state summary say the app's own
  lines are excluded, but that filter only runs on window lines, not on logcat lines (120).
- **Focus isn't checked.** The decision never looks at the focus line the watchdog already collects.
- **It's slow.** Headsets are checked one at a time, with two heavy reads each. A full-fleet pass takes
  minutes, not the 10 s interval the panel passes by default.

**Fix:**
- Only look at logcat lines newer than the last check (`logcat -d -T '<time>'`).
- Apply the package filter to logcat lines too.
- Require the prompt to show in the window list.
- Narrow the pattern using evidence.
- Check headsets in parallel, with a cap.

### M5. "Full Keepalive (reconnect+wake)" never reconnects — reading
**Where:** panel (2433–2438); sync_files.py `run_keepalive` (1646–1651).

**What:**
- The panel starts `sync_files.py --keepalive` without `--connect-file`. Without it, the keepalive only
  wakes headsets that are already connected: what Stay-Awake does, but every 20 minutes. The caption
  and the button both promise reconnects.
- Any unexpected exception ends the loop, because only KeyboardInterrupt is caught (1639–1677).

**Fix:**
- Either pass massConnect's own `~/.cxvr_massconnect/known_ips.txt` (already in host:port lines),
  filtered to the current subnet and connected in parallel with a cap, or relabel the row as wake-only.
- Catch and log errors in each cycle, so one bad cycle doesn't end the loop.

### M6. A reader thread that hits an unexpected error dies and leaves the panel stuck — reading
**Where:** panel `_run_command` (2157–2186) and the `_start_toggle` reader (2276–2303). Copied verbatim
into the Qt panel.

**What:**
- Output pipes are read with `text=True`, which decodes UTF-8 strictly. A single invalid byte raises
  UnicodeDecodeError, and `_run_command` only catches FileNotFoundError.
- After that:
  - No "done" is posted, so the action buttons stay disabled.
  - `finally` clears `current_proc`, so Interrupt reports "nothing running" and cleanup can't reach the
    process.
  - Nothing reads the pipe any more, so the script eventually blocks.
- A watchdog whose reader dies keeps showing as Running, and blocks the same way.
- It's unlikely, because most output is ASCII, but when it happens the only way out is a restart.

**Fix:**
- Open every text pipe with `encoding="utf-8", errors="replace"`.
- Add an `except Exception` that logs the error and still posts "done".
- Clear `current_proc` only if it is still this process.

### M7. One exception stops the Tk panel's log loop for good — reading
**Where:**
- `_poll_log_queue` (2103–2130).
- The cross-thread dictionary iterations: `_screencap_status_text` (2855–2858), the batch slots (3222),
  `action_batch_preview_toggle` (3324), and the process count in Kill ADB server (2330).

**What:**
- The loop reschedules itself only at its very end. Any exception skips `after(100, …)`. The log freezes,
  "done" messages are never handled, and the buttons stay disabled until a restart.
- A realistic trigger: `_screencap_status_text` iterates `scrcpy_procs.items()` while calling
  `p.poll()`, and a reader thread can delete an entry at the same moment (2929). That raises
  "dictionary changed size during iteration".
- In the Qt panel the timer keeps firing, so the panel survives. The item that raised is lost, though,
  and that item could be a "done".

**Fix:**
- Iterate over snapshots (`list(d.items())`).
- In the loop, wrap each item in try/except that logs the error, and reschedule in `finally`.

This is small and self-contained: a candidate for a critical fix to the frozen panel.

### M8. Closing the panel kills a running action without asking, and a stale sync brake is never cleared — reading
**Where:** `_on_close` (3814), `_cleanup_subprocesses` (3739–3765), `_run_command` (2159–2186).

**What:**
- **No confirmation.** Closing the window SIGKILLs whatever one-shot action is running:
  - mid-Connect: headsets can be left asleep between SLEEP and WAKE
  - mid-volume-set
  - mid-sync: a partial file is left behind
  - mid-delete
- **A stale sync brake.**
  - `sync_in_progress` is removed in the `finally` of the reader, a daemon thread. After a window close,
    that removal races interpreter shutdown.
  - After a crash, a kill or a power loss it never happens.
  - Nothing removes a stale file at startup, so an armed overheat watchdog or black-screen probe stays
    suppressed ("a content sync is running"), and nothing on screen says so.

**Fix:**
- If an action is running, name it and ask before closing, defaulting to No.
- At startup, delete `sync_in_progress` if the PID written in it isn't a running panel.
- Have the daemons log a sentinel whose PID is dead as stale.
- Show the brake state in the status strip.

### M9. v3.local writes: the backup isn't checked, and the new file is pushed over the live one — reading, unverified on the Go
**Where:** delete_video.py (120–134); sync_files.py (817–818 and 955–956, with their pushes).

**What:**
- **Unchecked backup.** The result of `cp v3.local v3.local.bak.<ts>` is ignored. On a full headset,
  which is a known condition on the 32 GB units, the backup fails silently.
- **Pushing over the live file.** In AOSP's adbd (`do_send` in file_sync_service), an existing file is
  deleted before the new one is written, and a failed transfer deletes the partial file. So a push that
  fails (a WiFi drop, a full disk) can leave no `v3.local` at all, and no backup either.
- **Possible race.** The running app could rewrite `v3.local` between our read and our push.

**Fix:**
- Check the `cp`.
- Push to `v3.local.cxvr_new`, check its size and JSON on the headset, then `mv` it over `v3.local` (a
  rename on the same filesystem is atomic). Stop at the first failure.
- Keep only the last few backups. Today one is added on every write, and they are never removed.

### M10. Volume: the loop reads the speaker's level, which may not be the output being changed — reading, unverified on the Go
**Where:** volumeNormalize.sh (50–56, 141–180).

**What:**
- **It may read the wrong output.** `read_volume_state` takes the second number of the `Current:` line,
  which is the first listed output: the speaker. Volume keys change the output in use. With headphones
  plugged in, the headphone level changes but the reading doesn't move.
  - The loop then presses up to 5 rounds × the difference. For example, from 11 to a target of 8 it can
    press DOWN up to 15 times, taking headphones to 0.
  - It then reports NOT CONFIRMED, in green (L11).
  - This matters only if headsets are ever used with headphones.
- **Presses to one headset run concurrently.** Each press is its own adb call, spread across 20 parallel
  slots. A headset that needs 10 presses can get up to 10 `input keyevent` calls at once, and each one
  starts a Java process on the headset. That may well be where the dropped presses the loop corrects for
  come from.

**Fix:**
- Read the stream's `Devices:` line and use that output's level. Confirm first with a snapshot taken
  with headphones plugged in.
- Send one job per headset, `input keyevent 25 25 25` in a single call (try it on one headset first),
  with headsets in parallel.

### M11. Fleet-wide commands start everything at once — reading
**Where:** screenRefresh.sh (19–29); sleepAll, wakeAll, powerOff, rebootAll; stayAwake.sh (44–48);
heartbeatMaintain.sh (23–35).

**What:**
- **Sleep → Wake** (the headtracking fix) sends 16 SLEEPs and 5 WAKEs per headset. For 70 headsets
  that's about 1,470 adb commands, 1,120 of them at once, and there's no final `wait`.
  volumeNormalize.sh's own notes say unthrottled parallel adb destabilized the adb server before, and a
  restarting adb server is exactly what sets off H1.
- **Stay-Awake** starts about 70 adb calls every 5 s without waiting for the previous batch.
- **Heartbeat** never pauses between passes. With only a few headsets connected, it pings each one about
  once a second.

**Fix:**
- Use massConnect's pattern (`xargs -P 20`) for every fleet-wide burst.
- Screen refresh: one SLEEP, confirm Asleep through `dumpsys power`, then WAKE, instead of 16 blind
  presses.
- Heartbeat: a minimum time per pass, for example 10 s.

### M12. The config can silently reset, and that re-hides every feature marked tested — reading
**Where:** `load_config` (274–285), `save_config` (287–289).

**What:**
- Corrupt JSON loads as the defaults, and the next save overwrites the file. `save_config` writes in
  place, so a crash or a power loss mid-write (a laptop battery at a venue) produces exactly that.
- Settings and tested marks are lost with no message.

**Fix:**
- Write to a temporary file, fsync, then `os.replace`.
- On a parse failure, keep the bad file as `config.json.corrupt-<time>` and say so.

### M13. Content Sync: the prune confirmation and the device list don't name their scope — reading
**Where:** `_confirm_prune_if_needed` (2740–2747), `_sync_cmd` (2718–2720); sync_files.py (1869–1871).

**What:**
- The prune dialog says "the device(s)". It doesn't say how many headsets, which ones, or which remote
  folder.
- Advanced › devices is a free-text box. A typo, or a headset that isn't connected, is dropped silently:
  sync_files.py filters the connected list and never reports allow-listed names that matched nothing.

**Fix:**
- Name the count or the serials, and the remote folder, in the dialog.
- Log allow-listed serials that aren't connected, and exit non-zero.
- In the Qt port (Phase 2), use a device picker instead of free text. That would be a new intentional
  difference for §6.

---

## Low

**massConnect.sh**
- **L1.** "Confirmed fixed" only means the three adb commands returned OK and the headset answers
  `get-state` (386–389). Nothing checks that it actually slept, and in the default path WAKE follows
  SLEEP immediately (351–356). That boot is then recorded as fixed and never retried. Consider polling
  `dumpsys power` for Asleep before waking. Unverified on the Go: whether a sub-second sleep applies the
  fix.
- **L2.** Retries reuse the transport ids read before attempt 1 (343, 357, 374, 392). If sleep and wake
  made a headset reconnect, every retry fails. Rebuild the map between attempts.
- **L3.** The comment at 558–569 says the background WiFi-policy pushes are in the panel's process
  group. `timeout` gives each one its own group (plan §14.2).
- **L4.** Temporary files leak:
  - A manual run that can't get the lock leaves `transport_map_file` behind (599–604).
  - `batch_fix_*.log` files pile up in `~/.cxvr_headtracking_fix/`.
  - No trap cleans up on interrupt.

**Small shell scripts**
- **L5.** `adb devices` runs without a timeout in almost every script. A wedged adb server hangs the
  script until you press Interrupt.
- **L6.** They always exit 0 and print nothing per headset, so `[exit code 0]` doesn't mean it worked.
  Heartbeat prints nothing for a headset that doesn't answer.
- **L7.** `screenRefresh.sh` has no final `wait` (25–29). The panel still waits for the WAKE jobs
  through the pipe.
- **L8.** A graceful Stop sends SIGINT. Backgrounded adb jobs in a non-interactive bash ignore it and
  outlive Stop until their timeout. Stop never checks that the process exited, and never escalates.
- **L9.** The `kill -0` parent checks could be fooled by PID reuse. Very unlikely, given Linux's large
  PID range.

**volumeNormalize.sh**
- **L10.** The first report and the final summary read headsets one at a time (100–108, 193–207), which
  takes minutes for the whole fleet.
- **L11.** "NOT CONFIRMED" shows in green. The log colours any line containing "confirmed" green unless it
  also contains FAIL (Tk `_append_log`; Qt 2446–2449). Check negative phrases first.
- **L12.** It always exits 0, even when headsets end up NOT CONFIRMED.

**captureDiagnostics.sh**
- **L13.** Two captures in the same second write to the same folder (142–150).
- **L14.** The screenshot fallback writes and then deletes `/sdcard/_cxvr_snap.png` (113–115), so it
  isn't strictly read-only, despite its header.
- **L15.** The panel's default target is ALL: about 70 parallel captures, screenshots included, over the
  show AP.

**delete_video.py**
- **L16.** It works through headsets one at a time, running `du -sk` on each (199, 277–280).
- **L17.** The panel uses the literal "ALL CONNECTED HEADSETS" (2010) instead of `ALL_DEVICES_LABEL`.
  The confirmation says "from: ALL CONNECTED HEADSETS" without a count.

**sync_files.py**
- **L18.** `run_adb` (173–179) decodes strictly and catches only TimeoutExpired. A UnicodeDecodeError
  from logcat output or a file name crashes the caller:
  - a device's sync, which is logged as CRASHED
  - a daemon's check of that headset, on every cycle
  - the keepalive loop
- **L19.** `batched_size_check` (510–515) splits at the *first* colon, so a file name containing a colon
  makes `int()` raise and crashes that device's sync. Use `rsplit(":", 1)`.
- **L20.** `is_protected_headjack_file` (444) tests `".bak" in name`, which also matches content such as
  `intro.bakery.mp4`. Those files are silently never synced. Match `.bak` only as a suffix.
- **L21.** Push retries (632–648) don't re-check free space between attempts.
- **L22.** Keep screen on (698–703) is never undone:
  - It sets a 24-hour screen timeout, turns on stay-awake and sends the proximity broadcasts.
  - The checkbox is saved as a panel setting, so every sync applies it again.
  - The GUI has no action to restore normal settings.
  - Its label doesn't mention that it also turns off proximity auto-standby.
- **L23.** A run where some headsets were skipped after a failed scan still exits 0 (1954–1956). CRASHED
  is logged without a traceback (1892).
- **L24.** Lines from parallel workers can merge, because `print()` writes the text and the newline
  separately (151–155). Use one write under a lock.

**Panel (both)**
- **L25.** Every action rewrites all 15 scripts in place (188–204, 1810–1822). Already in plan §12.
- **L26.** Waits on the main thread freeze the window:
  - Kill ADB server: up to 15 s (2344)
  - Refresh of the device list: up to 10 s (3056–3070)
  - Stopping batch preview: up to 11 s (3154)
- **L27.** The other-instance warning (3788) doesn't look for popupWatchdog.sh, overheatWatchdog.py or
  blackScreenProbe.py, the three that act on headsets.
- **L28.** Sleep doesn't warn that Stay-Awake (every 5 s), Keepalive or an armed probe will wake the
  headsets again.
- **L29.** `_run_command` posts "done" before its `finally` clears `current_proc` and the sync sentinel.
  In theory the next action's state could be cleared. Post "done" last.
- **L30.** The Tk log has no line cap and no per-tick cap, so a flood of output blocks the window. Both
  panels jump to the bottom on every new line, even while you're scrolled up reading.
- **L31.** Tk only: the mouse wheel changes a headset dropdown (plan §14.3, open decision).

## Qt panel only
- **Q1.** Only `sys.excepthook` is hooked (4327). Add `threading.excepthook` too, so a crash in a worker
  thread (M6) shows in the log when the panel was double-clicked.
- **Q2.** In the log pump, an exception in one item's handler loses that item. Wrap each item on its own.
- **Q3.** The generic `QPushButton:focus` rule (1135) also tints the sidebar buttons' border when they
  have focus. Cosmetic.
- **Q4.** `Collapsible` (1292) isn't used on any Phase 1 page, so it's untested until Phase 2.

## Port kit
- **K1.** Attributes guarded by `hasattr`: copied logic silently skips them when a page doesn't create
  them, and neither the integrity check nor the recorder notices. Five are unset today, all for later
  pages: `batch_preview_btn`, `batch_status_var`, `debug_status_var`, `debug_toggle_btn`,
  `screencap_status_var`. Add a check with a per-phase allowlist.
- **K2.** `compare.py`:
  - The navigation rule accepts *any* Qt title whenever Tk shows Main Menu. Pin it to the expected
    landing page.
  - Two empty recordings compare as a pass ("0 scenarios"). Fail when either side has no results.
- **K3.** `run_all.sh`:
  - All steps share one shell, so a `cd` in one step carries into the next.
  - There's no usage message.
  - `compare.py` and the rollback test use the system `python3`, not `PY311` or `VENV_PY`.
  - pyflakes doesn't check `tk_tests/`.
- **K4.** `record.py` deletes `config.json`, `show_mode` and `snapshots/` in `CONFIG_DIR`, and relies on
  the harness having already pointed HOME at a temporary folder. Add a guard that refuses to run against
  a real home.

---

## Improvements

1. **One throttled fan-out for fleet-wide work.**
   - In bash, `xargs -P N`; in Python, a thread pool of about 10.
   - One OK or FAILED line per headset, and a non-zero exit code if any failed.
   - This fixes M11, L5, L6, L10 and L16, and turns minutes into seconds for the probe, the overheat
     watchdog, Delete Video and the keepalive.
2. **Filter on the headset.** Pipe `dumpsys` through `grep` in the adb shell command, to cut AP traffic
   during shows (popup watchdog, overheat watchdog).
3. **One brake helper** shared by every daemon: `show_mode`, plus `sync_in_progress` with a PID check.
   Show the brake state in the status strip.
4. **Atomic writes** wherever state matters: the config, the embedded scripts, `v3.local` and
   `last_run_report.json`.
5. **A "last watchdog cycle" time** in the strip, so a stalled or skipping watchdog shows.
6. **Log.** Colour negative phrases first. Follow new output only when the view is already at the bottom.

## Already recorded elsewhere
- Plan §14, items 1–4: the stale Running row, `timeout` stragglers, the Tk mouse wheel, and Show Mode's
  scope.
- Plan §12: rewriting scripts via a temporary file and rename; the brief moment when Interrupt reports
  "nothing running".

## Suggested order
1. **Gather evidence first** with the Diagnostic Snapshot, one headset each:
   - a headset slept deliberately (M3)
   - a headset taken off a head (M3)
   - a headset with headphones plugged in (M10)
   - whether HOME returns to the app (M2)
   - the overheat prompt, the next time it appears (M4)
2. **Candidate critical fixes for the frozen panel.** Each needs your approval, is mirrored into Qt and is
   logged in the plan. All are small and contained:
   - **H1** (embedded script, so both files change and must stay byte-identical)
   - **M6**, **M7**, **M12**
3. **Behaviour changes to the daemons that act on headsets:**
   - **H2**, **M1** and **M2** now; **M3** and **M4** before anyone arms them.
   - Rule 2 puts these under Testing until you mark them tested.
   - H2 needs your decision on Show Mode.
   - Designing them is safety-critical detection logic (rule 3): Opus 5.5 at Max to design, Extra high to
     implement, High for the small fixes.
4. **Everything else** can go with Phase 2 or after cutover.

**Still open from Phase 1:**
- §14 items 1–3.
- D1–D5 (assumed).
- The double-click check on the laptop.
- Which features are marked tested there.

---

## Addendum, 3 Oct 2026: C1, missed by this audit
**C1 (Critical, reproduced).** The headtracking fix in massConnect.sh skips most headsets. Its
background `adb shell` calls read the device list the loop is reading, so the loop stops after about
10–15 headsets.
- The audit read these loops and missed this. It was found from the user's log of a 72-headset run: 40
  fixed, 32 failed, and every failure had an empty sleep result.
- Details, evidence and the fix are in `cxvr_audit_fix_plan.md` §3b (hotfix B0).


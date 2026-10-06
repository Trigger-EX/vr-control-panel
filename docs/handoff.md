# Handoff

## Goal
Maintain the CXVR Oculus Go fleet control panel. First ship hotfix B0 (critical bug C1). Then work through
the audit fix plan (Batches 1–4), then continue the PySide6 port (Phase 2 onward).

## Decisions and constraints
- Rules are in `CLAUDE.md`: GUI only, untested work goes under Testing, stronger model when it matters,
  safety principles, and no adb against the real fleet without the user's explicit OK.
- `cxvr_control_panel.py` (Tk, frozen, production) has md5 `fab822033fc7b83cf95b9bbf026ce6c1`.
  `cxvr_control_panel_qt.py` (Phase 1) has md5 `da5b000262234c5cf7f08d6be8ef7e57`.
- Fixes go into both files, and `EMBEDDED_SCRIPTS` stays byte-identical.
- Python 3.11; PySide6-Essentials 6.11.2.
- Fix-plan decisions A1–A8 are assumed. The Go supports 60/72 Hz only. Audio capture is dropped.

## Current state
- Port Phase 1 is done. Port kit v1 (`port_kit/`) was all green on 27 Sep.
- Audit: `docs/cxvr_code_audit_2026-09-30.md`. Fix plan: `docs/cxvr_audit_fix_plan.md`.
- Nothing has been implemented since Phase 1.
- C1: in `apply_headtracking_fix`, background `adb shell` calls read the `while read … < file` device list.
  The loop stops after about 10–15 headsets. Reproduced and fix proven in
  `repro/c1_headtracking_stdin/repro_c1.sh` (11/72 SLEEPs sent as shipped, 72/72 with `< /dev/null`).

## Open questions
- Approve B0?
- Which features are marked tested?
- Are headphones used at shows (and what about headset .116)?
- Confirm A1–A8 and D1–D5.
- The user's double-click check of the Qt panel.
- The evidence list (fix plan §9).

## Next step
1. Set up the environment and run `port_kit/run_all.sh cxvr_control_panel.py cxvr_control_panel_qt.py`.
2. Run the C1 repro.
3. Ask the user to approve B0, then build it in both files with a kit test and a full kit run.

Full detail: `docs/HANDOFF_DETAILED.md`.

## Chat
Base name: CXVR Phase 1 port, audit and fix plan
Run: 1

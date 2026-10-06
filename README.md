# CXVR control panel: hand-off bundle (6 Oct 2026)

Unzip this into a folder (ideally a git repository: `git init && git add -A && git commit -m baseline`) and
start Claude Code in it. Claude Code reads `CLAUDE.md` automatically. Then send "go". It should read
`docs/handoff.md` and `docs/HANDOFF_DETAILED.md` first.

| Path | What |
|---|---|
| `CLAUDE.md` | Standing rules and safety principles for Claude Code |
| `docs/handoff.md` | Short checkpoint: goal, state, open questions, next step |
| `docs/HANDOFF_DETAILED.md` | The full hand-off |
| `docs/cxvr_project_state_summary_v4.md` | What the panel does (sessions 2–4) |
| `docs/cxvr_pyside6_port_plan.md` | The port plan (phases, intentional differences, status) |
| `docs/cxvr_code_audit_2026-09-30.md` | The audit (plus the C1 addendum) |
| `docs/cxvr_audit_fix_plan.md` | The fix plan (B0, Batches 1–4) |
| `cxvr_control_panel.py` | Frozen Tk panel (production), md5 fab822033fc7b83cf95b9bbf026ce6c1 |
| `cxvr_control_panel_qt.py` | Qt panel, Phase 1, md5 da5b000262234c5cf7f08d6be8ef7e57 |
| `port_kit/` | Port kit v1 (`run_all.sh`) |
| `repro/c1_headtracking_stdin/` | Reproduction of C1 and proof of the B0 fix (fake adb only) |

Nothing in this bundle talks to real headsets.

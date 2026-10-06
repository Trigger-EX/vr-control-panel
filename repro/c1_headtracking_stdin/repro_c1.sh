#!/bin/bash
# Reproduces finding C1 (the headtracking fix skips most headsets) and checks the proposed fix.
#   ./repro_c1.sh PATH/TO/cxvr_control_panel.py
# Takes massConnect.sh out of the panel's EMBEDDED_SCRIPTS, cuts out the fix block of
# apply_headtracking_fix (from 'if [ ! -s "$fix_map_file" ]' to the end of the summary read), and runs it
# against a fake adb for 72 headsets: once as shipped, once with `< /dev/null` on the three background
# subshells (SLEEP, WAKE, reachability). No real adb or headset is touched.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
PANEL=$(readlink -f "${1:?usage: repro_c1.sh PANEL_FILE}")
WORK=$(mktemp -d)
python3 - "$PANEL" "$WORK" <<'PY'
import ast, sys
from pathlib import Path
panel, work = sys.argv[1], Path(sys.argv[2])
tree = ast.parse(open(panel, encoding="utf-8").read())
node = next(n for n in tree.body if isinstance(n, ast.Assign)
            and getattr(n.targets[0], "id", "") == "EMBEDDED_SCRIPTS")
script = ast.literal_eval(node.value)["massConnect.sh"].splitlines(keepends=True)
start = next(i for i, l in enumerate(script) if l.startswith('if [ ! -s "$fix_map_file" ]; then'))
end = next(i for i in range(start, len(script)) if script[i].strip() == 'rm -f "$summary_file"') + 1
assert script[end].strip() == "fi", script[end]
block = "".join(script[start:end + 1])
(work / "fixblock_as_shipped.sh").write_text(block)
fixed = block
for old in ('|| echo fail > "$scratch/$safe_name.sleep" ) &',
            'echo "$result" > "$scratch/$safe_name.wake"\n                ) &',
            '|| echo fail > "$scratch/$safe_name.state" ) &'):
    assert fixed.count(old) == 1, old
    fixed = fixed.replace(old, old[:-1] + "< /dev/null &")
(work / "fixblock_fixed.sh").write_text(fixed)
PY
run() {   # run BLOCK LABEL
    export FAKE_ADB_JOURNAL="$WORK/journal_$2"; : > "$FAKE_ADB_JOURNAL"
    out=$(PATH="$HERE/fakebin:$PATH" WORK="$WORK" BLOCK="$1" bash -c '
        set -u
        HEADTRACK_STATE_DIR="$WORK/state_$RANDOM"; mkdir -p "$HEADTRACK_STATE_DIR"
        VISUAL_CHECK=0; TABLET_CHECK_DELAY=20; confirmed_this_run=0; failed_this_run=0
        fix_map_file=$(mktemp); transport_map_file=$(mktemp)
        for i in $(seq 1 72); do printf "172.16.16.%s:5555\t%s\tboot%s\n" "$i" "$i" "$i" >> "$fix_map_file"; done
        source "$BLOCK"
        echo "RESULT confirmed=$confirmed_this_run failed=$failed_this_run"' 2>&1)
    echo "$2: $(echo "$out" | grep RESULT | cut -d" " -f2-)  SLEEP sent: $(grep -c 'keyevent 223' "$FAKE_ADB_JOURNAL")  WAKE sent: $(grep -c 'keyevent 224' "$FAKE_ADB_JOURNAL")"
}
run "$WORK/fixblock_as_shipped.sh" "as shipped"
run "$WORK/fixblock_fixed.sh"      "with fix  "
echo "(expected: as shipped, only a fraction of the 72 SLEEPs go out; with the fix, 72 SLEEPs, 432 WAKEs, 72 confirmed)"
rm -rf "$WORK"

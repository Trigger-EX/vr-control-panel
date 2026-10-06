#!/bin/bash
# Runs the whole port kit. Every step must pass before and after any change.
#
#   ./run_all.sh TK_PANEL QT_PANEL [OUT_DIR]
#
# Environment (defaults match the workspace set up per the plan, section 11):
#   PY311    a Python 3.11 WITH Tkinter and WITHOUT PySide6   (uv python find 3.11)
#   VENV_PY  a Python 3.11 venv WITH PySide6-Essentials 6.11.2 and pyflakes
#   VHOME    a folder holding .pyvenv/bin/python with PySide6 (for the launch tests);
#            created with uv if missing
set -u
KIT=$(cd "$(dirname "$0")" && pwd)
TK=$(readlink -f "$1"); QT=$(readlink -f "$2"); OUT=${3:-$KIT/out}
PY311=${PY311:-$(uv python find 3.11)}
VENV_PY=${VENV_PY:-$HOME/venv311/bin/python}
VHOME=${VHOME:-$HOME/vhome}
mkdir -p "$OUT"
XVFB=(xvfb-run -a -s "-screen 0 1600x1200x24")
declare -a NAMES STATUS
step() {   # step NAME command...
    local name=$1; shift
    echo; echo "=================== $name"
    "$@" > "$OUT/$name.log" 2>&1
    local rc=$?
    grep -v "propagateSizeHints\|does not support raise\|invalid command name\|while executing\|\"after\" script\|^\"" \
        "$OUT/$name.log" | grep -E "FAIL|DIFF|ERROR|Traceback|[0-9]+ / [0-9]+|scenarios|passed|identical" | tail -25
    NAMES+=("$name"); STATUS+=("$rc")
}

compile_all() {
    "$PY311" -m py_compile "$TK" && "$VENV_PY" -m py_compile "$QT" && echo "py_compile ok (Python 3.11)" &&
    "$VENV_PY" -m pyflakes "$QT" "$KIT"/*.py "$KIT"/common/*.py && echo "pyflakes ok" &&
    for f in "$KIT"/relaunch_tests.sh "$KIT"/fakebin_lifecycle/adb; do bash -n "$f" || return 1; done &&
    "$VENV_PY" - "$QT" <<'EOF'
import ast, subprocess, sys, tempfile, os
tree = ast.parse(open(sys.argv[1]).read())
node = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "EMBEDDED_SCRIPTS")
scripts = ast.literal_eval(node.value)
bad = []
for name, body in scripts.items():
    if name.endswith(".sh"):
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
            f.write(body)
        if subprocess.run(["bash", "-n", f.name]).returncode:
            bad.append(name)
        os.unlink(f.name)
    else:
        compile(body, name, "exec")
print(f"bash -n / compile on {len(scripts)} embedded scripts: {'ok' if not bad else bad}")
sys.exit(1 if bad else 0)
EOF
}

tk_suites() {
    cd "$KIT/tk_tests" || return 1
    local rc=0
    for t in t_stream t_term t_behavior; do
        CXVR_PANEL="$TK" CXVR_TEST_HOME=$(mktemp -d) timeout 300 "${XVFB[@]}" "$PY311" $t.py || rc=1
    done
    return $rc
}

differential() {
    cd "$KIT" || return 1
    timeout 1200 "${XVFB[@]}" "$PY311" record.py --panel tk --file "$TK" --out "$OUT/tk.json" | grep -v ": ok$"
    local a=${PIPESTATUS[0]}
    timeout 1200 "$VENV_PY" record.py --panel qt --file "$QT" --out "$OUT/qt.json" | grep -v ": ok$"
    local b=${PIPESTATUS[0]}
    python3 compare.py "$OUT/tk.json" "$OUT/qt.json"
    local c=$?
    [ $a -eq 0 ] && [ $b -eq 0 ] && [ $c -eq 0 ]
}

launch() {
    if [ ! -x "$VHOME/.pyvenv/bin/python" ]; then
        uv venv "$VHOME/.pyvenv" --python 3.11 -q && uv pip install -q --python "$VHOME/.pyvenv/bin/python" \
            PySide6-Essentials==6.11.2 || return 1
    fi
    bash "$KIT/relaunch_tests.sh" "$QT" "$PY311" "$VHOME"
}

step 01_compile        compile_all
step 02_integrity      "$VENV_PY" "$KIT/t_integrity.py" "$TK" "$QT"
step 03_stream_tk      "$PY311" "$KIT/t_stream.py" "$TK"
step 04_stream_qt      "$VENV_PY" "$KIT/t_stream.py" "$QT"
step 05_tk_suites      tk_suites
step 06_differential   differential
step 07_qt_behavior    "$VENV_PY" "$KIT/t_qt_behavior.py" "$QT"
step 08_lifecycle      "$VENV_PY" "$KIT/t_lifecycle.py" "$QT"
step 09_visual         "$VENV_PY" "$KIT/t_visual.py" "$QT" "$OUT/screenshots"
step 10_visual_125     env QT_SCALE_FACTOR=1.25 "$VENV_PY" "$KIT/t_visual.py" "$QT" "$OUT/screenshots" 800x640 1536x832
step 11_rollback       "${XVFB[@]}" python3 "$KIT/t_rollback.py" "$QT" "$TK" "$VENV_PY" "$PY311"
step 12_launch         launch
step 13_c1_stdin       "$VENV_PY" "$KIT/t_c1_stdin.py" "$TK" "$QT"

echo; echo "=================== summary (logs in $OUT)"
fail=0
for i in "${!NAMES[@]}"; do
    if [ "${STATUS[$i]}" -eq 0 ]; then echo "  pass  ${NAMES[$i]}"; else echo "  FAIL  ${NAMES[$i]}"; fail=1; fi
done
exit $fail

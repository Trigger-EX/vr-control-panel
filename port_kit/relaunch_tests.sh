#!/bin/bash
# Launch tests for the "double-click in Thunar" relaunch (see the plan, section 4.9).
# Usage: relaunch_tests.sh FILE BASE_PY VENV_HOME
#   FILE       the Qt file to start (it must support --screenshot DIR and exit by itself)
#   BASE_PY    a Python 3.11 WITHOUT PySide6 (stands in for the laptop's system Python)
#   VENV_HOME  a folder containing .pyvenv/bin/python WITH PySide6 (stands in for /home/user)
# Build them like the laptop's:  uv python install 3.11
#   uv venv VENV_HOME/.pyvenv --python 3.11 && uv pip install --python VENV_HOME/.pyvenv/bin/python PySide6-Essentials==6.11.2
FILE=$(readlink -f "$1"); BASE=$2; VHOME=$3; W=$(mktemp -d)
mkdir -p "$W/pybin" "$W/emptyhome"; ln -s "$BASE" "$W/pybin/python3"
pass=0; fail=0
check() { if [ "$1" = "$2" ]; then echo "PASS $3"; pass=$((pass+1)); else echo "FAIL $3 (exit $1, expected $2)"; fail=$((fail+1)); fi; }
cd /tmp
timeout 90 env HOME="$VHOME" "$BASE" "$FILE" --screenshot "$W/s1" >/dev/null 2>&1; check $? 0 "open-with system Python (venv python is a symlink to it)"
timeout 90 env HOME="$VHOME" PATH="$W/pybin:/usr/bin:/bin" "$FILE" --screenshot "$W/s2" >/dev/null 2>&1; check $? 0 "executable file via its first line"
(cd "$(dirname "$FILE")" && timeout 90 env HOME="$VHOME" "$BASE" "$(basename "$FILE")" --screenshot "$W/s3" >/dev/null 2>&1); check $? 0 "relative path from the file's folder"
out=$(timeout 60 env HOME="$W/emptyhome" CXVR_NO_DIALOG=1 "$BASE" "$FILE" --screenshot "$W/s4" 2>&1); check $? 1 "no venv: clear error, exit 1"
out=$(timeout 60 env HOME="$W/emptyhome" CXVR_NO_DIALOG=1 CXVR_QT_PYTHON="$BASE" "$BASE" "$FILE" 2>&1); check $? 1 "CXVR_QT_PYTHON same as current: no relaunch"
timeout 90 env HOME="$VHOME" "$VHOME/.pyvenv/bin/python" "$FILE" --screenshot "$W/s6" >/dev/null 2>&1; check $? 0 "venv Python directly"
out=$(timeout 60 env HOME="$W/emptyhome" CXVR_NO_DIALOG=1 CXVR_QT_PYTHON="$W/pybin/python3" "$BASE" "$FILE" 2>&1); rc=$?
case "$out" in *"$W/pybin/python3"*) check $rc 1 "loop guard: relaunched once into a Python without PySide6, then stopped";; *) check "no-relaunch" 1 "loop guard (message didn't name the relaunched Python)";; esac
echo "relaunch tests: $pass passed, $fail failed"; rm -rf "$W"; [ $fail -eq 0 ]

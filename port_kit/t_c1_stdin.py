"""Hotfix B0 / finding C1: the headtracking fix must send SLEEP/WAKE to every headset.

  t_c1_stdin.py PANEL [PANEL ...]

For each panel: cut the fix block out of the embedded massConnect.sh and run it against a fake adb
(repro/c1_headtracking_stdin/fakebin/adb) that reads stdin like the real client, for 72 headsets.
  * as embedded:  all 72 confirmed, 72 SLEEPs, 432 WAKEs.
  * mutation check: with the `< /dev/null` redirects removed (the pre-B0 script) the same test must fail,
    so this test proves it detects C1.
  * sync_files.run_adb must pass stdin=DEVNULL.
Also checks EMBEDDED_SCRIPTS is byte-identical across the given panels. No real adb is touched."""
import ast, os, subprocess, sys, tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parent
FAKEBIN = KIT.parent / "repro" / "c1_headtracking_stdin" / "fakebin"
N = 72
fails = 0
total = 0


def check(ok, msg):
    global fails, total
    total += 1
    print(("PASS " if ok else "FAIL ") + msg)
    fails += 0 if ok else 1


def scripts_of(panel):
    tree = ast.parse(Path(panel).read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "EMBEDDED_SCRIPTS")
    return ast.literal_eval(node.value)


def fix_block(script):
    lines = script.splitlines(keepends=True)
    start = next(i for i, l in enumerate(lines) if l.startswith('if [ ! -s "$fix_map_file" ]; then'))
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == 'rm -f "$summary_file"') + 1
    assert lines[end].strip() == "fi"
    return "".join(lines[start:end + 1])


def run_block(block):
    work = tempfile.mkdtemp()
    bf = os.path.join(work, "block.sh")
    Path(bf).write_text(block)
    journal = os.path.join(work, "journal")
    Path(journal).write_text("")
    env = dict(os.environ, PATH=f"{FAKEBIN}:{os.environ['PATH']}", FAKE_ADB_JOURNAL=journal, WORK=work, BLOCK=bf)
    assert subprocess.run("which adb", shell=True, env=env, capture_output=True, text=True).stdout.strip() == str(FAKEBIN / "adb")
    out = subprocess.run(["bash", "-c", '''set -u
        HEADTRACK_STATE_DIR="$WORK/state"; mkdir -p "$HEADTRACK_STATE_DIR"
        VISUAL_CHECK=0; TABLET_CHECK_DELAY=20; confirmed_this_run=0; failed_this_run=0
        fix_map_file=$(mktemp); transport_map_file=$(mktemp)
        for i in $(seq 1 %d); do printf "172.16.16.%%s:5555\\t%%s\\tboot%%s\\n" "$i" "$i" "$i" >> "$fix_map_file"; done
        source "$BLOCK"
        echo "RESULT $confirmed_this_run $failed_this_run"''' % N], env=env, capture_output=True, text=True, timeout=300).stdout
    res = next(l for l in out.splitlines() if l.startswith("RESULT")).split()
    j = Path(journal).read_text()
    return int(res[1]), int(res[2]), j.count("keyevent 223"), j.count("keyevent 224")


panels = sys.argv[1:]
base = None
for p in panels:
    s = scripts_of(p)
    if base is None:
        base = s
    check(s == base, f"{Path(p).name}: EMBEDDED_SCRIPTS identical to {Path(panels[0]).name}")
    block = fix_block(s["massConnect.sh"])
    check(s["massConnect.sh"].count(") < /dev/null &") == 4, f"{Path(p).name}: 4 backgrounded subshells (detect/sleep/wake/state) have stdin from /dev/null")
    conf, failed, sl, wk = run_block(block)
    check((conf, failed, sl, wk) == (N, 0, N, 6 * N), f"{Path(p).name}: as embedded confirmed={conf} failed={failed} SLEEP={sl} WAKE={wk}")
    old = block.replace("< /dev/null &", "&")
    conf, failed, sl, wk = run_block(old)
    check(sl < N and conf < N, f"{Path(p).name}: mutation (pre-B0 script) is caught: confirmed={conf} SLEEP={sl} of {N}")
    check("stdin=subprocess.DEVNULL" in s["sync_files.py"].split("def run_adb")[1].split("def adb_devices")[0],
          f"{Path(p).name}: sync_files.run_adb uses stdin=DEVNULL")
print(f"c1 stdin {total - fails} / {total}")
sys.exit(1 if fails else 0)

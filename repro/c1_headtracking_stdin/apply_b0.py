"""Replayable edit for hotfix B0 (finding C1). Usage: apply_b0.py PANEL.py [PANEL2.py ...]
Edits the embedded massConnect.sh and sync_files.py in place by exact repr() replacement."""
import ast, sys

SH_EDITS = [   # (old, new) -- each must match exactly once
    ('            echo "needs_fix\t$boot_id\t$last_fixed_boot_id\t$uptime_s" > "$scratch_detect/$safe_name.result"\n        ) &\n',
     '            echo "needs_fix\t$boot_id\t$last_fixed_boot_id\t$uptime_s" > "$scratch_detect/$safe_name.result"\n        ) < /dev/null &\n'),
    ('|| echo fail > "$scratch/$safe_name.sleep" ) &', '|| echo fail > "$scratch/$safe_name.sleep" ) < /dev/null &'),
    ('echo "$result" > "$scratch/$safe_name.wake"\n                ) &', 'echo "$result" > "$scratch/$safe_name.wake"\n                ) < /dev/null &'),
    ('|| echo fail > "$scratch/$safe_name.state" ) &', '|| echo fail > "$scratch/$safe_name.state" ) < /dev/null &'),
]
PY_EDITS = [
    ('            ["adb"] + args, capture_output=True, text=True, timeout=timeout\n',
     '            ["adb"] + args, capture_output=True, text=True, timeout=timeout,\n            stdin=subprocess.DEVNULL,\n'),
]

def patch(path):
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "EMBEDDED_SCRIPTS")
    scripts = ast.literal_eval(node.value)
    for name, edits in (("massConnect.sh", SH_EDITS), ("sync_files.py", PY_EDITS)):
        old_body = scripts[name]
        body = old_body
        for old, new in edits:
            assert body.count(old) == 1, (name, old)
            body = body.replace(old, new)
        assert src.count(repr(old_body)) == 1, name
        src = src.replace(repr(old_body), repr(body))
    open(path, "w", encoding="utf-8").write(src)

for p in sys.argv[1:]:
    patch(p)
    print("patched", p)

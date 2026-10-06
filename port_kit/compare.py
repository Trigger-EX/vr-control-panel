#!/usr/bin/env python3
"""Compares a Tk recording with a Qt recording (record.py output), scenario by
scenario and field by field. A difference is allowed only if a rule below
explains it -- each rule cites the plan's list of intentional differences
(section 6) or names the later port phase that closes it. Anything else is a
bug, and the exit code is 1.

usage: compare.py tk.json qt.json [--verbose]"""
import difflib
import json
import sys


def _events_without(events, kind):
    return [e for e in events if e[0] != kind]


# (rule id, explanation, predicate(field, tk_value, qt_value, tk_result, qt_result) -> bool)
RULES = [
    ("6.1+6.8 navigation",
     "The Tk panel starts on (and returns to) its Main Menu; the Qt panel has a sidebar instead and opens on Connect.",
     lambda f, t, q, tr, qr: f == "state.title" and t == "Main Menu"),
    ("phase 2: terminal",
     "The Tk panel opened its terminal session when terminal.shell became enabled; the Qt terminal arrives in phase 2.",
     lambda f, t, q, tr, qr: f in ("events", "startup") and _events_without(t, "terminal_session") == q
     and any(e[0] == "terminal_session" for e in t)),
]


def compare(tk, qt, verbose=False):
    tk_by = {r["name"]: r for r in tk["results"]}
    qt_by = {r["name"]: r for r in qt["results"]}
    names = [r["name"] for r in tk["results"]]
    bad, allowed, identical = [], [], 0
    missing = sorted(set(tk_by) ^ set(qt_by))
    for name in names:
        if name not in qt_by:
            continue
        t, q = tk_by[name], qt_by[name]
        if "error" in t or "error" in q:
            bad.append((name, "error", t.get("error", ""), q.get("error", "")))
            continue
        fields = []
        for key in ("startup", "events", "extra", "log", "config_changes", "sentinels"):
            fields.append((key, t.get(key), q.get(key)))
        for key in sorted(set(t["state"]) | set(q["state"])):
            fields.append((f"state.{key}", t["state"].get(key), q["state"].get(key)))
        any_diff = False
        for field, tv, qv in fields:
            if tv == qv:
                continue
            any_diff = True
            rule = next((r for r in RULES if r[2](field, tv, qv, t, q)), None)
            if rule:
                allowed.append((name, field, rule[0]))
            else:
                bad.append((name, field, tv, qv))
        if not any_diff:
            identical += 1
    return names, identical, allowed, bad, missing


def show(value):
    return json.dumps(value, indent=1, ensure_ascii=False, sort_keys=True).splitlines()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    verbose = "--verbose" in sys.argv
    tk, qt = (json.load(open(p)) for p in args[:2])
    names, identical, allowed, bad, missing = compare(tk, qt, verbose)
    for name, field, *values in bad:
        print(f"DIFF  {name}  [{field}]")
        if field == "error":
            print("  tk error:\n" + "".join("    " + line + "\n" for line in str(values[0]).splitlines()[-6:]))
            print("  qt error:\n" + "".join("    " + line + "\n" for line in str(values[1]).splitlines()[-6:]))
            continue
        for line in difflib.unified_diff(show(values[0]), show(values[1]), "tk", "qt", lineterm="", n=2):
            print("    " + line)
    if verbose:
        for name, field, rule in allowed:
            print(f"allowed  {name}  [{field}]  ({rule})")
    rules_used = {}
    for _n, _f, rule in allowed:
        rules_used[rule] = rules_used.get(rule, 0) + 1
    if qt.get("thread_violations"):
        print(f"THREAD VIOLATIONS in the Qt run: {qt['thread_violations']}")
    print(f"\n{len(names)} scenarios: {identical} identical, "
          f"{len(set(n for n, *_ in allowed) - set(n for n, *_ in bad))} differ only as allowed, "
          f"{len(set(n for n, *_ in bad))} with unexplained differences")
    for rule, count in sorted(rules_used.items()):
        print(f"  allowed by '{rule}': {count} field(s)")
    if missing:
        print(f"scenarios recorded on only one side: {missing}")
    sys.exit(1 if bad or missing or qt.get("thread_violations") else 0)


if __name__ == "__main__":
    main()

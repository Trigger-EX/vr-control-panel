#!/usr/bin/env python3
"""Integrity checks between the frozen Tk panel and the Qt panel.

  * EMBEDDED_SCRIPTS: the same 15 scripts, byte for byte, and the same source text.
  * Each verbatim block (constants, embedded scripts, process helpers, terminal
    backend, palette + HELP) appears in the Qt file character for character.
  * Each copied ControlPanel method (common/logic_map.py COPIED) is the Tk method
    after the declared substitutions -- nothing else may differ.
  * Every Tk method is accounted for exactly once (copied, rewritten, dropped, later).
  * No method is defined twice in either ControlPanel.
  * The Qt panel defines everything the copied logic calls on self.

usage: t_integrity.py TK_PANEL QT_PANEL"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "common"))
import logic_map  # noqa: E402
import srcmap  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  {detail}"))


def embedded(tree):
    node = srcmap.top_level_nodes(tree)["EMBEDDED_SCRIPTS"]
    return ast.literal_eval(node.value)


def main(tk_path, qt_path):
    tk_src, qt_src = (open(p, encoding="utf-8").read() for p in (tk_path, qt_path))
    tk_tree, qt_tree = ast.parse(tk_src), ast.parse(qt_src)

    tk_scripts, qt_scripts = embedded(tk_tree), embedded(qt_tree)
    check("EMBEDDED_SCRIPTS: same 15 names", sorted(tk_scripts) == sorted(qt_scripts) and len(tk_scripts) == 15,
          sorted(set(tk_scripts) ^ set(qt_scripts)))
    for name in sorted(tk_scripts):
        check(f"EMBEDDED_SCRIPTS[{name}] byte-identical", tk_scripts[name] == qt_scripts.get(name))

    for block in logic_map.VERBATIM_BLOCKS:
        tk_text = srcmap.block_text(tk_src, tk_tree, block)
        try:
            qt_text = srcmap.block_text(qt_src, qt_tree, block)
        except Exception as e:
            check(f"verbatim block '{block[0]}'", False, e)
            continue
        check(f"verbatim block '{block[0]}' ({tk_text.count(chr(10))} lines) identical", tk_text == qt_text)

    tk_methods = srcmap.class_methods(tk_tree, "ControlPanel")   # also asserts no duplicates
    qt_methods = srcmap.class_methods(qt_tree, "ControlPanel")
    check("no method defined twice in either ControlPanel", True)

    groups = {"copied": set(logic_map.COPIED), "rewritten": set(logic_map.REWRITTEN),
              "dropped": set(logic_map.DROPPED), "later": set(logic_map.LATER)}
    listed = [n for g in groups.values() for n in g]
    check("each Tk method listed in exactly one group", len(listed) == len(set(listed)),
          sorted(n for n in listed if listed.count(n) > 1))
    check("every Tk method accounted for", set(listed) == set(tk_methods),
          {"unlisted": sorted(set(tk_methods) - set(listed)), "not in Tk": sorted(set(listed) - set(tk_methods))})

    changed = []
    for name in logic_map.COPIED:
        want = srcmap.substituted(name, srcmap.method_text(tk_src, tk_tree, "ControlPanel", name))
        have = srcmap.method_text(qt_src, qt_tree, "ControlPanel", name) if name in qt_methods else None
        if want != have:
            changed.append(name)
    check(f"{len(logic_map.COPIED)} copied methods identical to Tk after substitutions", not changed, changed)

    qt_top = srcmap.top_level_nodes(qt_tree)
    for name in logic_map.REWRITTEN:
        target = logic_map.REWRITTEN[name]
        if target.isidentifier():
            check(f"rewritten {name} -> {target} exists in Qt", target in qt_methods or target in qt_top)
    for name, phase in logic_map.LATER.items():
        if name.startswith(("show_menu_", "_render_testing_")):
            check(f"later page {name} (phase {phase}) has a placeholder", name in qt_methods)

    # Every self.<method>(...) the copied logic calls must exist on the Qt panel.
    called = set()
    for name in logic_map.COPIED:
        for node in ast.walk(ast.parse("class X:\n" + srcmap.method_text(qt_src, qt_tree, "ControlPanel", name))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and \
                    isinstance(node.func.value, ast.Name) and node.func.value.id == "self":
                called.add(node.func.attr)
    missing = sorted(c for c in called if c not in qt_methods)
    check("every self.method() the copied logic calls exists in the Qt panel", not missing, missing)

    print(f"integrity {sum(results)} / {len(results)}")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main(*sys.argv[1:3]) else 1)

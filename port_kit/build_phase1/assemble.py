#!/usr/bin/env python3
"""Phase 1 assembler: builds cxvr_control_panel_qt.py from the frozen Tkinter
panel plus the Qt-only parts in build/parts/. Everything taken from the Tk file
is sliced out of it (AST line ranges, exact anchors), never retyped.

From Phase 2 on, the Qt file itself is the source that gets edited; this script
is kept in the port kit as the record of how Phase 1 put it together.

usage: assemble.py TK_PANEL OUT_FILE
"""
import ast
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))         # inside the port kit
sys.path.insert(0, os.path.join(HERE, "..", "kit", "common"))  # the original workspace layout
import logic_map  # noqa: E402
import srcmap  # noqa: E402

TK_MD5 = "fab822033fc7b83cf95b9bbf026ce6c1"   # the frozen session-4 panel (3,869 lines)


def part(name):
    with open(os.path.join(HERE, "parts", name), encoding="utf-8") as f:
        return f.read()


def main(tk_path, out_path):
    raw = open(tk_path, "rb").read()
    digest = hashlib.md5(raw).hexdigest()
    if digest != TK_MD5:
        sys.exit(f"{tk_path} isn't the frozen Tk panel this was built against (md5 {digest})")
    src = raw.decode("utf-8")
    tree = ast.parse(src)
    blocks = {b[0]: srcmap.block_text(src, tree, b) for b in logic_map.VERBATIM_BLOCKS}

    # Every Tk method must be accounted for exactly once.
    tk_methods = srcmap.class_methods(tree, "ControlPanel")
    groups = [set(logic_map.COPIED), set(logic_map.REWRITTEN), set(logic_map.DROPPED), set(logic_map.LATER)]
    union = set().union(*groups)
    assert sum(len(g) for g in groups) == len(union), "a method is listed in two groups"
    missing, extra = set(tk_methods) - union, union - set(tk_methods)
    assert not missing and not extra, (missing, extra)
    order = sorted(logic_map.COPIED, key=lambda n: tk_methods[n][0])
    assert order == logic_map.COPIED, "COPIED isn't in the Tk file's order"

    copied = []
    for name in logic_map.COPIED:
        copied.append(srcmap.substituted(name, srcmap.method_text(src, tree, "ControlPanel", name)))

    pieces = [
        part("10_header.py"),
        "\n",
        blocks["constants"], "\n\n",
        blocks["embedded_scripts"], "\n\n",
        blocks["process_helpers"], "\n\n",
        blocks["terminal_backend"], "\n\n",
        blocks["palette_and_help"],
        part("30_compat.py"),
        part("40_design.py"),
        part("50_panel_ui.py"),
        "\n".join(copied),
        part("90_main.py"),
    ]
    out = "".join(pieces)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out)
    os.chmod(out_path, 0o755)
    print(f"wrote {out_path}: {out.count(chr(10))} lines, {len(out.encode())} bytes; "
          f"{len(copied)} methods copied, {len(blocks)} verbatim blocks")


if __name__ == "__main__":
    main(*sys.argv[1:3])

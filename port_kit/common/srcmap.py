"""Locating blocks and methods in the panel sources (shared by the assembler
and the integrity test). Everything is found through the AST or an exact,
unique line -- never a regex over the whole file."""
import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import logic_map  # noqa: E402


def lines_of(src):
    return src.splitlines(keepends=True)


def top_level_nodes(tree):
    nodes = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            nodes[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    nodes[target.id] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            nodes[node.target.id] = node
    return nodes


def _unique_line(lines, text):
    hits = [i for i, line in enumerate(lines) if line.strip() == text]
    if len(hits) != 1:
        raise AssertionError(f"expected exactly one line {text!r}, found {len(hits)}")
    return hits[0]


def block_span(src, tree, anchor, end_name):
    """(start, end) line indices, end exclusive, of one VERBATIM_BLOCKS entry."""
    lines = lines_of(src)
    kind, text = anchor
    start = _unique_line(lines, text)
    if kind == "banner":
        above = lines[start - 1].strip()
        if not (above.startswith("# ---") or above.startswith("# ===")):
            raise AssertionError(f"no rule line above banner {text!r}")
        start -= 1
    node = top_level_nodes(tree)[end_name]
    return start, node.end_lineno


def block_text(src, tree, block):
    _name, anchor, end_name = block
    start, end = block_span(src, tree, anchor, end_name)
    return "".join(lines_of(src)[start:end])


def class_methods(tree, class_name):
    """name -> (first line index incl. decorators, end exclusive) for one class."""
    cls = top_level_nodes(tree)[class_name]
    methods = {}
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            first = min([node.lineno] + [d.lineno for d in node.decorator_list])
            if node.name in methods:
                raise AssertionError(f"{class_name}.{node.name} is defined twice")
            methods[node.name] = (first - 1, node.end_lineno)
    return methods


def method_text(src, tree, class_name, name):
    start, end = class_methods(tree, class_name)[name]
    return "".join(lines_of(src)[start:end])


def substituted(name, text):
    for old, new in logic_map.GLOBAL_SUBSTITUTIONS:
        text = text.replace(old, new)
    for old, new in logic_map.EXTRA_SUBSTITUTIONS.get(name, []):
        if text.count(old) < 1:
            raise AssertionError(f"extra substitution {old!r} not found in {name}")
        text = text.replace(old, new)
    for bad in logic_map.TK_ONLY_NAMES:
        if bad in text:
            raise AssertionError(f"copied method {name} still mentions {bad!r} after substitution")
    return text

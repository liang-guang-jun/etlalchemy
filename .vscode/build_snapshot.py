#!/usr/bin/env python3
"""Concatenate package sources into one dependency-ordered snapshot file.

Only files that git does not ignore are considered. Modules are ordered so that
every module appears after the modules it imports at import time; imports inside
function bodies and ``if TYPE_CHECKING`` blocks are ignored because they never
run while the module is imported. Import cycles are appended at the end and
reported on stderr.

The rendered snapshot is written to ``--out`` and, unless ``--no-copy`` is
passed, copied to the system clipboard so it can be pasted into a review or a
chat without opening the file.

Usage:
    uv run python .vscode/build_snapshot.py
    uv run python .vscode/build_snapshot.py --root etlalchemy --out snapshot.py
    uv run python .vscode/build_snapshot.py --no-copy
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

import pyperclip

DEFAULT_ROOT = Path("etlalchemy")
DEFAULT_OUT = Path(".cache/code-snapshot.py")
RULE = "# " + "=" * 77


def git_tracked_files(root: Path) -> list[Path]:
    """Return files under root that git tracks or does not ignore."""
    completed = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            root.as_posix(),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(
        path
        for path in (Path(line) for line in completed.stdout.splitlines())
        if path.is_file()
    )


def module_name(path: Path, root: Path) -> str:
    """Return the dotted module name of a source file below root."""
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join([root.name, *parts])


def _is_type_checking(node: ast.expr) -> bool:
    """Return whether an if-test is ``TYPE_CHECKING`` or ``typing.TYPE_CHECKING``."""
    if isinstance(node, ast.Name):
        return node.id == "TYPE_CHECKING"
    if isinstance(node, ast.Attribute):
        return node.attr == "TYPE_CHECKING"
    return False


def _import_time_nodes(tree: ast.AST) -> list[ast.AST]:
    """Return nodes that execute while the module is imported.

    Function bodies are deferred until the function is called and ``if
    TYPE_CHECKING`` blocks never execute, so neither creates an ordering
    dependency between snapshot modules.
    """
    nodes: list[ast.AST] = []
    stack = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            stack.extend(node.orelse)
            continue
        nodes.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return nodes


def imported_names(path: Path) -> set[str]:
    """Return the dotted module names imported when a source file is imported."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    names: set[str] = set()
    for node in _import_time_nodes(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


def resolve_import(name: str, known: set[str]) -> str | None:
    """Map an imported name onto the longest known module prefix."""
    candidate = name
    while candidate:
        if candidate in known:
            return candidate
        candidate = candidate.rpartition(".")[0]
    return None


def dependency_graph(files: dict[str, Path]) -> dict[str, set[str]]:
    """Return each module mapped to the snapshot modules it imports."""
    known = set(files)
    graph: dict[str, set[str]] = {}
    for module, path in files.items():
        dependencies: set[str] = set()
        for name in imported_names(path):
            resolved = resolve_import(name, known)
            if resolved is not None and resolved != module:
                dependencies.add(resolved)
        graph[module] = dependencies
    return graph


def dependency_order(graph: dict[str, set[str]]) -> tuple[list[str], list[str]]:
    """Order modules dependencies-first and return any modules left in cycles."""
    remaining = {module: set(dependencies) for module, dependencies in graph.items()}
    ordered: list[str] = []
    while remaining:
        ready = sorted(module for module, deps in remaining.items() if not deps)
        if not ready:
            break
        for module in ready:
            ordered.append(module)
            del remaining[module]
        for dependencies in remaining.values():
            dependencies.difference_update(ready)
    return ordered, sorted(remaining)


def render(files: dict[str, Path], ordered: list[str], cyclic: list[str]) -> str:
    """Render the snapshot text with one comment banner per file."""
    header = (
        "# Code snapshot generated by .vscode/build_snapshot.py.\n"
        f"# {len(ordered)} files, dependencies before dependents.\n"
    )
    if cyclic:
        header += (
            f"# {len(cyclic)} modules are part of an import cycle and were "
            "appended last: " + ", ".join(cyclic) + ".\n"
        )
    blocks = [
        "\n".join(
            (
                RULE,
                f"# file: {files[module].as_posix()}",
                RULE,
                files[module].read_text(encoding="utf-8").rstrip("\n"),
            )
        )
        for module in ordered
    ]
    return header + "\n" + "\n\n".join(blocks) + "\n"


def copy_to_clipboard(text: str) -> bool:
    """Copy the snapshot to the clipboard and report whether it worked."""
    try:
        pyperclip.copy(text)
    except pyperclip.PyperclipException as exc:
        print(f"warning: could not copy to clipboard: {exc}", file=sys.stderr)
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    """Write the snapshot file, copy it to the clipboard, and report the outcome."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--no-copy",
        action="store_true",
        help="Write the snapshot file without copying it to the clipboard.",
    )
    args = parser.parse_args(argv)

    root: Path = args.root
    out: Path = args.out
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    files = {
        module_name(path, root): path
        for path in git_tracked_files(root)
        if path.suffix == ".py"
    }
    if not files:
        print(f"error: no python files found under {root}", file=sys.stderr)
        return 1

    ordered, cyclic = dependency_order(dependency_graph(files))
    if cyclic:
        print(f"warning: import cycle among: {', '.join(cyclic)}", file=sys.stderr)
    ordered.extend(cyclic)

    snapshot = render(files, ordered, cyclic)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(snapshot, encoding="utf-8")
    print(f"wrote {out} ({len(ordered)} files)")

    if not args.no_copy and copy_to_clipboard(snapshot):
        print(f"copied {out} to clipboard")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
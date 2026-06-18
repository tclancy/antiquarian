"""Pure layout-logic for the surveyed-files index (#108/#109).

Turns a flat list of file paths into a nested folder/file tree and derives
the initial open-depth from an information budget. No HTML, no I/O — the
renderer (``render.py``) walks the structure this module computes and emits
``<details>``. See ``docs/visualizing-at-scale.md`` (principles 1, 2, 5).
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Default information budget: rows a reader takes in at a glance (principle 1).
DEFAULT_FILE_BUDGET = 30


@dataclass(frozen=True)
class FileNode:
    """A leaf: one surveyed file. ``path`` is the full original path."""

    name: str
    path: str


@dataclass
class FolderNode:
    """An interior node: a folder grouping files and sub-folders.

    ``file_count`` is the recursive count of files beneath this folder — used
    for the ``name (count)`` summary line.
    """

    name: str
    path: str
    children: list = field(default_factory=list)
    file_count: int = 0


Node = FileNode | FolderNode


def build_file_tree(paths: list[str]) -> list[Node]:
    """Build a sorted folder/file forest from flat ``paths``.

    Returns the root-level nodes. Folders sort before files, each group
    alphabetically; folders carry a recursive ``file_count``.
    """
    root = FolderNode(name="", path="")
    for path in paths:
        _insert(root, path.split("/"), path)
    _finalize(root)
    return root.children


def _insert(folder: FolderNode, segments: list[str], full_path: str) -> None:
    """Insert ``full_path`` (split into ``segments``) under ``folder``."""
    *folders, filename = segments
    cur = folder
    for seg in folders:
        cur = _subfolder(cur, seg)
    cur.children.append(FileNode(name=filename, path=full_path))


def _subfolder(parent: FolderNode, name: str) -> FolderNode:
    """Return the named child folder of ``parent``, creating it if absent."""
    for child in parent.children:
        if isinstance(child, FolderNode) and child.name == name:
            return child
    path = f"{parent.path}/{name}" if parent.path else name
    child = FolderNode(name=name, path=path)
    parent.children.append(child)
    return child


def _finalize(folder: FolderNode) -> int:
    """Sort ``folder`` recursively and return its recursive file count."""
    count = 0
    for child in folder.children:
        if isinstance(child, FolderNode):
            count += _finalize(child)
        else:
            count += 1
    folder.children.sort(key=_sort_key)
    folder.file_count = count
    return count


def _sort_key(node: Node) -> tuple[int, str]:
    """Folders (0) before files (1), then alphabetical by name."""
    return (0 if isinstance(node, FolderNode) else 1, node.name)


def choose_open_depth(tree: list[Node], target: int = DEFAULT_FILE_BUDGET) -> int:
    """Largest open-depth ``D`` whose visible-node count stays within ``target``.

    A folder at depth ``d`` renders open iff ``d < D``; a node is *visible*
    when all its ancestor folders are open, i.e. when its depth ``<= D``. So
    ``visible(D)`` counts nodes at tree-depth ``<= D`` and is monotonic in
    ``D``. We return the largest ``D`` with ``visible(D) <= target``, floored
    at 0 (the root is always shown). See visualizing-at-scale.md, principle 2.
    """
    depths = list(_node_depths(tree, 0))
    if not depths:
        return 0
    best = 0
    for d in range(0, max(depths) + 1):
        if sum(1 for nd in depths if nd <= d) <= target:
            best = d
        else:
            break
    return best


def _node_depths(nodes: list[Node], depth: int):
    """Yield the tree-depth of every node (folders and files); root is 0."""
    for node in nodes:
        yield depth
        if isinstance(node, FolderNode):
            yield from _node_depths(node.children, depth + 1)


def siblings_for_file(file_path: str, all_files: list[str]) -> list[str]:
    """Return the files that share the same directory as ``file_path``.

    "Same directory" means the parent path component(s) match exactly:
    ``src/a.py`` and ``src/b.py`` are siblings; ``src/api/views.py`` is not.
    Root-level files (no ``/`` in the path) are siblings of each other.

    ``file_path`` does not need to appear in ``all_files`` — callers that
    exclude the current file from their survey list still get the correct
    sibling set.  Returns a sorted list.
    """
    parts = file_path.split("/")
    parent_dir = "/".join(parts[:-1])  # "" for root-level files

    result = []
    for fp in all_files:
        fp_parts = fp.split("/")
        fp_parent = "/".join(fp_parts[:-1])
        if fp_parent == parent_dir:
            result.append(fp)
    return sorted(result)

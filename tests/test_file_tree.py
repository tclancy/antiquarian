"""Tests for the pure file-tree layout module (#108/#109).

``file_tree`` turns a flat list of surveyed file paths into a nested
folder/file tree and derives the initial open-depth from an information
budget — no HTML, no I/O (see docs/visualizing-at-scale.md, principle 5).
These tests pin the tree-building and the depth formula across shapes and
sizes so the adaptive rule is proven independently of rendering.
"""

from __future__ import annotations

from antiquarian.file_tree import (
    FileNode,
    FolderNode,
    build_file_tree,
    choose_open_depth,
)


class TestBuildFileTree:
    def test_empty_list_is_empty_forest(self):
        assert build_file_tree([]) == []

    def test_single_root_file(self):
        tree = build_file_tree(["README.md"])
        assert tree == [FileNode(name="README.md", path="README.md")]

    def test_nested_paths_group_into_folders(self):
        tree = build_file_tree(["pkg/a.py", "pkg/b.py"])
        assert len(tree) == 1
        folder = tree[0]
        assert isinstance(folder, FolderNode)
        assert folder.name == "pkg"
        assert folder.path == "pkg"
        assert folder.children == [
            FileNode(name="a.py", path="pkg/a.py"),
            FileNode(name="b.py", path="pkg/b.py"),
        ]

    def test_folders_sort_before_files_then_alphabetical(self):
        # root has folder "zoo", folder "a", and a bare file "b.py"
        tree = build_file_tree(["b.py", "zoo/x.py", "a/y.py"])
        names = [n.name for n in tree]
        assert names == ["a", "zoo", "b.py"]

    def test_children_sorted_folders_then_files(self):
        tree = build_file_tree(["pkg/z.py", "pkg/sub/deep.py", "pkg/a.py"])
        folder = tree[0]
        child_names = [c.name for c in folder.children]
        assert child_names == ["sub", "a.py", "z.py"]

    def test_folder_file_count_is_recursive(self):
        tree = build_file_tree(
            ["pkg/a.py", "pkg/sub/b.py", "pkg/sub/c.py", "pkg/sub/deep/d.py"]
        )
        pkg = tree[0]
        assert pkg.file_count == 4
        sub = next(c for c in pkg.children if isinstance(c, FolderNode))
        assert sub.name == "sub"
        assert sub.file_count == 3

    def test_deep_path_builds_nested_folders(self):
        tree = build_file_tree(["a/b/c/leaf.py"])
        a = tree[0]
        assert a.name == "a" and a.path == "a"
        b = a.children[0]
        assert isinstance(b, FolderNode) and b.path == "a/b"
        c = b.children[0]
        assert isinstance(c, FolderNode) and c.path == "a/b/c"
        assert c.children == [FileNode(name="leaf.py", path="a/b/c/leaf.py")]


class TestChooseOpenDepth:
    def test_small_tree_opens_fully(self):
        tree = build_file_tree(["a/x.py", "a/y.py", "b.py"])
        # depths: folder a(0), x(1), y(1), b(0) -> visible(1)=4 <= 30
        assert choose_open_depth(tree, target=30) == 1

    def test_wide_flat_root_collapses_to_zero(self):
        paths = [f"f{i:02d}.py" for i in range(40)]
        tree = build_file_tree(paths)
        # 40 root files, visible(0)=40 > 30 -> floor at 0
        assert choose_open_depth(tree, target=30) == 0

    def test_opens_to_top_folder_summaries_when_files_overflow(self):
        # 5 top folders, 10 files each: visible(0)=5, visible(1)=55
        paths = [f"d{f}/file{i}.py" for f in range(5) for i in range(10)]
        tree = build_file_tree(paths)
        assert choose_open_depth(tree, target=30) == 0

    def test_opens_one_level_when_it_fits(self):
        # 5 top folders, 3 files each: visible(0)=5, visible(1)=20 <= 30
        paths = [f"d{f}/file{i}.py" for f in range(5) for i in range(3)]
        tree = build_file_tree(paths)
        assert choose_open_depth(tree, target=30) == 1

    def test_three_level_cut_at_middle(self):
        # 2 top folders, each 3 subfolders, each 5 files
        # depths: 2 at d0, 6 at d1, 30 at d2 -> visible: 2, 8, 38
        paths = [
            f"t{t}/s{s}/file{i}.py"
            for t in range(2)
            for s in range(3)
            for i in range(5)
        ]
        tree = build_file_tree(paths)
        assert choose_open_depth(tree, target=30) == 1

    def test_empty_tree_is_depth_zero(self):
        assert choose_open_depth([], target=30) == 0

    def test_respects_custom_target(self):
        paths = [f"d{f}/file{i}.py" for f in range(5) for i in range(3)]
        tree = build_file_tree(paths)
        # tighter budget of 5 fits only the folder summaries (visible(0)=5)
        assert choose_open_depth(tree, target=5) == 0

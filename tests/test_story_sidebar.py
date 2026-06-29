"""Tests for the directory-navigation sidebar on story pages (#138).

TDD: these tests are written before the implementation. They define the contract:

  - ``siblings_for_file`` (pure, in file_tree.py) — which files share a directory.
  - ``_render_story_sidebar`` (render.py) — the sidebar HTML.
  - ``render_story_page`` with sidebar — integration: new keyword params, layout.

Only the *sidebar* is in scope for this PR. Commit-bubble timeline and
issue/PR links are explicitly out of scope and have no tests here.
"""

from __future__ import annotations


from antiquarian.file_tree import siblings_for_file, window_siblings
from antiquarian.render import (
    STORY_SIDEBAR_WINDOW,
    _render_story_sidebar,
    render_story_page,
)


# ---------------------------------------------------------------------------
# Pure logic: siblings_for_file
# ---------------------------------------------------------------------------


class TestSiblingsForFile:
    def test_returns_siblings_in_same_nested_dir(self):
        files = ["a/foo.py", "a/bar.py", "b/baz.py"]
        result = siblings_for_file("a/foo.py", files)
        assert "a/foo.py" in result
        assert "a/bar.py" in result
        assert "b/baz.py" not in result

    def test_root_level_files_share_root_dir(self):
        files = ["README.md", "setup.py", "src/main.py"]
        result = siblings_for_file("README.md", files)
        assert "README.md" in result
        assert "setup.py" in result
        assert "src/main.py" not in result

    def test_result_is_sorted(self):
        files = ["a/z.py", "a/a.py", "a/m.py"]
        result = siblings_for_file("a/z.py", files)
        assert result == sorted(result)

    def test_empty_all_files_returns_empty(self):
        assert siblings_for_file("a/foo.py", []) == []

    def test_only_file_in_dir_returns_itself(self):
        result = siblings_for_file("a/foo.py", ["a/foo.py", "b/bar.py"])
        assert result == ["a/foo.py"]

    def test_deep_nesting_only_matches_same_dir(self):
        # src/api/views.py and src/api/urls.py are siblings;
        # src/models.py is NOT a sibling (different dir).
        files = ["src/api/views.py", "src/api/urls.py", "src/models.py"]
        result = siblings_for_file("src/api/views.py", files)
        assert "src/api/views.py" in result
        assert "src/api/urls.py" in result
        assert "src/models.py" not in result

    def test_file_not_in_all_files_still_works(self):
        # Current file may not be in all_files (e.g. it was excluded from survey).
        result = siblings_for_file("a/foo.py", ["a/bar.py", "a/baz.py"])
        assert result == ["a/bar.py", "a/baz.py"]


# ---------------------------------------------------------------------------
# Pure logic: window_siblings — ±N cap centered on current file (#138 item 5)
# ---------------------------------------------------------------------------


class TestWindowSiblings:
    def test_short_list_returned_unchanged(self):
        # Fewer items than 2*window+1 — no slicing happens.
        sibs = ["a.py", "b.py", "c.py"]
        assert window_siblings(sibs, "b.py", window=5) == sibs

    def test_default_window_is_five_each_side(self):
        # Build 21 files with current in the dead center at index 10.
        sibs = [f"f{i:02d}.py" for i in range(21)]
        result = window_siblings(sibs, "f10.py")
        # 5 above + current + 5 below = 11 items.
        assert len(result) == 11
        assert result[0] == "f05.py"
        assert result[-1] == "f15.py"
        assert "f10.py" in result

    def test_current_at_start_clamps_left(self):
        sibs = [f"f{i:02d}.py" for i in range(21)]
        result = window_siblings(sibs, "f00.py", window=5)
        # current + 5 below = 6 items, no items above.
        assert result == [f"f{i:02d}.py" for i in range(0, 6)]

    def test_current_at_end_clamps_right(self):
        sibs = [f"f{i:02d}.py" for i in range(21)]
        result = window_siblings(sibs, "f20.py", window=5)
        # 5 above + current = 6 items, no items below.
        assert result == [f"f{i:02d}.py" for i in range(15, 21)]

    def test_current_not_in_list_centers_on_insertion_point(self):
        # Current was excluded from survey but other siblings exist.
        # Alphabetical insertion point of "ccc" between "bbb" and "ddd"
        # is index 2; the window centers there.
        sibs = ["aaa", "bbb", "ddd", "eee", "fff"]
        result = window_siblings(sibs, "ccc", window=1)
        # window=1 → 1 item below the insertion point, plus the next one
        # alphabetically; with insertion at index 2, window covers [1..3].
        assert "bbb" in result
        assert "ddd" in result

    def test_window_zero_returns_only_current(self):
        sibs = ["a", "b", "c", "d", "e"]
        assert window_siblings(sibs, "c", window=0) == ["c"]

    def test_empty_siblings_returns_empty(self):
        assert window_siblings([], "a.py") == []


# ---------------------------------------------------------------------------
# Rendering: _render_story_sidebar
# ---------------------------------------------------------------------------


class TestRenderStorySidebar:
    def test_current_file_marked_as_current(self):
        files = ["src/a.py", "src/b.py"]
        html = _render_story_sidebar(
            "src/a.py", files, {"src__a.py.md", "src__b.py.md"}
        )
        # The current file must carry a visual marker.
        assert "nav-current" in html
        # Its basename appears in the output.
        assert "a.py" in html

    def test_sibling_with_story_is_linked(self):
        files = ["src/a.py", "src/b.py"]
        html = _render_story_sidebar("src/a.py", files, {"src__b.py.md"})
        # Relative link — story pages are flat in the same directory.
        assert 'href="src__b.py.html"' in html

    def test_sibling_without_story_is_not_linked(self):
        files = ["src/a.py", "src/b.py"]
        html = _render_story_sidebar("src/a.py", files, set())
        # b.py should appear but without a clickable link.
        assert "b.py" in html
        assert 'href="src__b.py.html"' not in html

    def test_unlinked_sibling_marked_grey(self):
        # Item 4 of the #138 spec: unlinked siblings render in grey via
        # the .nav-unlinked class — kept (not omitted) so the reader can
        # see "this file exists but has no story page yet."
        files = ["src/a.py", "src/b.py"]
        html = _render_story_sidebar("src/a.py", files, {"src__a.py.md"})
        assert "nav-unlinked" in html

    def test_parent_nav_links_to_broadsheet(self):
        # The parent-nav link always targets the broadsheet's index.html —
        # the only navigation surface a story page can return to.
        files = ["src/a.py", "src/b.py"]
        html = _render_story_sidebar("src/a.py", files, set())
        assert 'href="../index.html"' in html

    def test_subdir_uses_parent_arrow_label(self):
        # In a subdir, the parent-nav reads "../" — short, unambiguous,
        # mirrors the shell idiom for "up one". Check the visible label
        # text rather than the URL (which also contains "../").
        files = ["src/api/views.py", "src/api/urls.py"]
        html = _render_story_sidebar("src/api/views.py", files, set())
        assert ">../</a>" in html
        # The full folder path must NOT appear as a breadcrumb anymore (#138 item 2).
        assert "nav-breadcrumb" not in html
        assert "nav-sep" not in html

    def test_root_uses_back_arrow_label(self):
        # At the project root, "../" is meaningless — use a back-arrow.
        # (The string "../" still appears inside the href="../index.html"
        # URL — that's a path, not the rendered label — so check the
        # visible link text directly.)
        files = ["foo.py", "bar.py"]
        html = _render_story_sidebar("foo.py", files, set())
        assert ">← broadsheet</a>" in html
        assert ">../</a>" not in html

    def test_subdir_marker_class_on_parent_nav(self):
        # CSS hook so we can typeset "../" as code without affecting
        # the "← broadsheet" form at the root.
        files = ["src/a.py", "src/b.py"]
        html = _render_story_sidebar("src/a.py", files, set())
        assert "nav-parent--subdir" in html
        files = ["a.py", "b.py"]
        html = _render_story_sidebar("a.py", files, set())
        assert "nav-parent--root" in html

    def test_long_sibling_list_is_windowed(self):
        # 21 siblings, current in the middle → at most ±5 around it (#138 item 5).
        files = [f"src/f{i:02d}.py" for i in range(21)]
        html = _render_story_sidebar("src/f10.py", files, set())
        # Within-window basenames appear; far-out ones do not.
        assert "f10.py" in html
        assert "f05.py" in html
        assert "f15.py" in html
        # Beyond the ±5 window — must be omitted from the sidebar.
        assert "f00.py" not in html
        assert "f20.py" not in html

    def test_windowing_cap_matches_module_constant(self):
        # If someone bumps STORY_SIDEBAR_WINDOW, the rendered output should
        # follow without test churn.
        n = STORY_SIDEBAR_WINDOW * 2 + 5  # comfortably more than the window
        files = [f"src/f{i:02d}.py" for i in range(n)]
        html = _render_story_sidebar(f"src/f{n // 2:02d}.py", files, set())
        # Count rendered <li class="nav-file …"> entries.
        rendered = html.count('<li class="nav-file')
        assert rendered == 2 * STORY_SIDEBAR_WINDOW + 1

    def test_no_siblings_other_than_self_returns_empty(self):
        # Only the current file in its directory — sidebar adds no navigation value.
        html = _render_story_sidebar("src/a.py", ["src/a.py"], set())
        assert html == ""

    def test_empty_all_files_returns_empty(self):
        html = _render_story_sidebar("src/a.py", [], set())
        assert html == ""

    def test_returns_nav_element(self):
        files = ["src/a.py", "src/b.py"]
        html = _render_story_sidebar("src/a.py", files, set())
        assert "<nav" in html

    def test_root_level_sibling_link_has_correct_filename(self):
        # A root-level file foo.py should link to bar.py.html (no extra underscores).
        files = ["foo.py", "bar.py"]
        html = _render_story_sidebar("foo.py", files, {"bar.py.md"})
        assert 'href="bar.py.html"' in html


# ---------------------------------------------------------------------------
# Integration: render_story_page with sidebar
# ---------------------------------------------------------------------------


class TestRenderStoryPageWithSidebar:
    def test_sidebar_injected_when_all_files_provided(self):
        files = ["src/a.py", "src/b.py"]
        html = render_story_page(
            "src/a.py",
            "# Origin\nThe story.",
            "myproject",
            all_files=files,
            files_with_stories={"src__a.py.md", "src__b.py.md"},
        )
        assert '<nav class="story-nav"' in html
        assert "story-layout" in html

    def test_no_sidebar_when_all_files_omitted(self):
        html = render_story_page("src/a.py", "# Origin\nThe story.", "myproject")
        # The nav element must not appear (CSS class definition doesn't count).
        assert '<nav class="story-nav"' not in html

    def test_no_sidebar_for_sole_file_in_its_dir(self):
        html = render_story_page(
            "src/a.py",
            "# Origin\nThe story.",
            "myproject",
            all_files=["src/a.py"],
            files_with_stories=set(),
        )
        # No sidebar when there are no siblings.
        assert '<nav class="story-nav"' not in html

    def test_print_css_hides_sidebar(self):
        files = ["src/a.py", "src/b.py"]
        html = render_story_page(
            "src/a.py",
            "# Origin\nThe story.",
            "myproject",
            all_files=files,
            files_with_stories={"src__a.py.md"},
        )
        # @media print rules must reference the nav class so the sidebar is
        # suppressed on paper. Both are guaranteed to be in the embedded CSS.
        assert "@media print" in html
        assert ".story-nav" in html  # class rule appears in the print CSS block

    def test_backward_compat_old_signature_unchanged(self):
        # Three-arg call must still work and return valid HTML.
        html = render_story_page("a.py", "some story", "proj")
        assert "proj" in html
        assert "a.py" in html

    def test_story_layout_wrapper_always_present(self):
        # Even without sidebar, the layout wrapper exists for structural consistency.
        html = render_story_page("a.py", "some story", "proj")
        assert "story-layout" in html

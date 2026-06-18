"""Tests for the directory-navigation sidebar on story pages (#138).

TDD: these tests are written before the implementation. They define the contract:

  - ``siblings_for_file`` (pure, in file_tree.py) — which files share a directory.
  - ``_render_story_sidebar`` (render.py) — the sidebar HTML.
  - ``render_story_page`` with sidebar — integration: new keyword params, layout.

Only the *sidebar* is in scope for this PR. Commit-bubble timeline and
issue/PR links are explicitly out of scope and have no tests here.
"""

from __future__ import annotations


from antiquarian.file_tree import siblings_for_file
from antiquarian.render import _render_story_sidebar, render_story_page


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

    def test_breadcrumb_contains_broadsheet_link(self):
        files = ["src/a.py", "src/b.py"]
        html = _render_story_sidebar("src/a.py", files, set())
        assert 'href="../index.html"' in html

    def test_breadcrumb_contains_dir_segments(self):
        files = ["src/api/views.py", "src/api/urls.py"]
        html = _render_story_sidebar("src/api/views.py", files, set())
        assert "src" in html
        assert "api" in html

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

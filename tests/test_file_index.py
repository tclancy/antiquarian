"""Integration tests for the collapsible, searchable file index (#108/#109).

These pin the rendering contract: the flat ``<ul>`` of surveyed files becomes
a nested ``<details>`` tree opened to the computed budget-depth, with a live
search control and print rules that force the whole tree open. The adaptive
*logic* is proven in test_file_tree.py; here we only assert it is wired in.
"""

from __future__ import annotations

from antiquarian.render import _render_file_index, render_page


def _timeline() -> dict:
    return {
        "full_span": {
            "start": "2020-01-01T00:00:00+00:00",
            "end": "2026-01-01T00:00:00+00:00",
            "days": 2192,
        },
        "active_windows": [],
        "gaps": [],
    }


def _page(files: list[str], **kwargs) -> str:
    return render_page(
        "proj",
        {"files": files, "generated_at": "2026-06-17"},
        {},
        _timeline(),
        "",
        None,
        **kwargs,
    )


class TestFileIndexRendering:
    def test_nested_folders_render_as_details(self):
        out = _render_file_index(["pkg/a.py", "pkg/b.py"], set())
        assert "<details" in out
        assert "<summary" in out
        # folder summary carries the name and its recursive file count
        assert "pkg" in out
        assert "2" in out

    def test_root_file_renders_as_leaf_not_folder(self):
        out = _render_file_index(["README.md"], set())
        assert "README.md" in out
        assert "<details" not in out

    def test_file_with_story_page_is_linked(self):
        out = _render_file_index(["src/a.py"], {"src__a.py.md"})
        assert 'href="stories/' in out
        assert "a.py" in out

    def test_leaf_carries_no_prose(self):
        # #121: the leaf is name + link only; no description span.
        out = _render_file_index(["src/a.py"], {"src__a.py.md"})
        assert "file-desc" not in out

    def test_overflowing_tree_collapses_deep_folders(self):
        # 5 top folders x 10 files: opens to top summaries, sub-content collapsed.
        paths = [f"d{f}/file{i}.py" for f in range(5) for i in range(10)]
        out = _render_file_index(paths, set())
        # at least one collapsed folder (a <details> without the open attribute)
        assert "<details>" in out

    def test_small_tree_opens_every_folder(self):
        out = _render_file_index(["pkg/a.py", "pkg/b.py"], set())
        assert "<details open>" in out
        assert "<details>" not in out  # nothing left collapsed

    def test_search_control_present(self):
        out = _render_file_index(["pkg/a.py"], set())
        assert "file-search" in out

    def test_empty_files_is_empty_string(self):
        assert _render_file_index([], set()) == ""


class TestFileIndexInPage:
    def test_page_embeds_tree_and_search_script(self):
        html = _page(["pkg/a.py", "pkg/b.py", "top.py"])
        assert "<details" in html
        assert "file-search" in html
        assert "<script" in html  # live-search enhancement

    def test_page_has_print_rules_forcing_tree_open(self):
        html = _page(["pkg/a.py"])
        assert "@media print" in html
        # print must force disclosures open and hide the search box
        assert ".file-search" in html

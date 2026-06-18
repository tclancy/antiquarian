"""Tests for the arc overlay on the swimlane (#119, PR-B).

Decisive commits link to their story page and name their arc on hover; bubbles
carry their arc slugs so the hover highlight (next task) can light real co-arc
commits. Honest: marks only, never a band.
"""

from __future__ import annotations

from antiquarian.render import render_swimlane

_TIMELINE = {
    "full_span": {
        "start": "2020-01-01T00:00:00+00:00",
        "end": "2026-01-01T00:00:00+00:00",
        "days": 2192,
    },
    "active_windows": [],
    "gaps": [],
}


def _lane(commits):
    return {
        "author": "Ada",
        "commit_count": len(commits),
        "total_loc": 9,
        "email": "a@b.c",
        "commits": commits,
    }


def _commit(
    sha, arcs, *, ts="2021-06-01T00:00:00+00:00", add=3, dele=2, subj="do a thing"
):
    return {
        "short_sha": sha,
        "timestamp": ts,
        "date": ts[:10],
        "additions": add,
        "deletions": dele,
        "subject": subj,
        "arcs": arcs,
        "files_changed": [],
    }


def test_bubble_has_class_and_data_arcs():
    out = render_swimlane(
        {"lanes": [_lane([_commit("abc123", ["transport-api"])])]}, _TIMELINE, []
    )
    assert 'class="commit-bubble"' in out
    assert 'data-arcs="transport-api"' in out


def test_non_decisive_bubble_has_empty_data_arcs():
    out = render_swimlane({"lanes": [_lane([_commit("abc123", [])])]}, _TIMELINE, [])
    assert 'data-arcs=""' in out


def test_decisive_bubble_names_arc_in_tooltip_when_lookup_given():
    lookup = {"transport-api": {"name": "Transport API rework", "story_href": None}}
    out = render_swimlane(
        {"lanes": [_lane([_commit("abc123", ["transport-api"])])]},
        _TIMELINE,
        [],
        arc_lookup=lookup,
    )
    assert "Transport API rework" in out


def test_decisive_bubble_carries_story_url_not_link():
    lookup = {
        "transport-api": {
            "name": "Transport API rework",
            "story_href": "stories/httpx___client.py.html",
            "color": "#ff2d95",
        }
    }
    out = render_swimlane(
        {"lanes": [_lane([_commit("abc123", ["transport-api"])])]},
        _TIMELINE,
        [],
        arc_lookup=lookup,
    )
    assert 'data-story-url="stories/httpx___client.py.html"' in out
    assert "<a href=" not in out  # no navigate-away wrap on the bubble


def test_no_lookup_keeps_data_arcs_but_no_link():
    out = render_swimlane(
        {"lanes": [_lane([_commit("abc123", ["transport-api"])])]}, _TIMELINE, []
    )
    assert 'data-arcs="transport-api"' in out
    assert "<a href=" not in out  # no lookup → no story link


from antiquarian.render import render_broadsheet  # noqa: E402


def _page():
    data = {
        "project": "p",
        "timeline": _TIMELINE,
        "todos": [],
        "swimlane": {
            "lanes": [
                _lane([_commit("abc123", ["a-slug"]), _commit("def456", ["a-slug"])])
            ]
        },
        "arc_band": {
            "arc_count": 1,
            "arcs": [
                {
                    "arc_number": 1,
                    "name": "An arc",
                    "slug": "a-slug",
                    "file_path": "a.py",
                    "commits": [],
                    "commit_count": 0,
                    "datable_count": 0,
                }
            ],
        },
        "file_lifespans": [],
        "files": [],
        "generated_at": "2026-06-18",
    }
    return render_broadsheet(data)


def test_highlight_css_and_script_present():
    html = _page()
    assert ".commit-xref" in html
    assert "data-arcs" in html
    assert "<script" in html


def test_no_arc_commits_get_inert_empty_data_arcs():
    # a commit with no arcs renders an inert bubble (empty data-arcs → the
    # script's mouseenter guard skips it, so no mass-highlight is possible)
    data = {
        "project": "p",
        "timeline": _TIMELINE,
        "todos": [],
        "swimlane": {"lanes": [_lane([_commit("zzz999", [])])]},
        "arc_band": {"arc_count": 0, "arcs": []},
        "file_lifespans": [],
        "files": [],
        "generated_at": "2026-06-18",
    }
    html = render_broadsheet(data)
    assert 'data-arcs=""' in html
    assert html.strip().endswith("</html>")  # complete document, no crash


def test_tooltip_includes_when_and_files():
    c = _commit("abc123", ["transport-api"])
    c["date"] = "2021-06-01"
    c["files_changed"] = ["httpx/_client.py", "httpx/_models.py"]
    out = render_swimlane({"lanes": [_lane([c])]}, _TIMELINE, [])
    assert "2021-06-01" in out
    assert "httpx/_client.py" in out and "httpx/_models.py" in out


def test_tooltip_summarizes_many_files():
    c = _commit("abc123", [])
    c["date"] = "2021-06-01"
    c["files_changed"] = ["a.py", "b.py", "c.py", "d.py"]
    out = render_swimlane({"lanes": [_lane([c])]}, _TIMELINE, [])
    assert "4 files changed" in out


def test_dim_the_rest_css_present():
    from antiquarian.render import render_broadsheet

    data = {
        "project": "p",
        "timeline": _TIMELINE,
        "todos": [],
        "swimlane": {"lanes": [_lane([_commit("abc123", ["a-slug"])])]},
        "arc_band": {"arc_count": 0, "arcs": []},
        "file_lifespans": [],
        "files": [],
        "generated_at": "2026-06-18",
    }
    html = render_broadsheet(data)
    assert "xref-dim" in html  # the hover-dim class is wired in CSS + script


def test_decisive_bubble_carries_arc_color():
    lookup = {
        "transport-api": {
            "name": "Transport API rework",
            "story_href": None,
            "color": "#ff2d95",
        }
    }
    out = render_swimlane(
        {"lanes": [_lane([_commit("abc123", ["transport-api"])])]},
        _TIMELINE,
        [],
        arc_lookup=lookup,
    )
    assert 'data-arc-color="#ff2d95"' in out


def test_non_decisive_bubble_has_no_arc_color():
    out = render_swimlane({"lanes": [_lane([_commit("abc123", [])])]}, _TIMELINE, [])
    assert "data-arc-color=" not in out


def test_broadsheet_assigns_neon_colors_and_grow_css():
    from antiquarian.render import render_broadsheet, NEON_ARC_COLORS

    data = {
        "project": "p",
        "timeline": _TIMELINE,
        "todos": [],
        "swimlane": {"lanes": [_lane([_commit("abc123", ["a-slug"])])]},
        "arc_band": {
            "arc_count": 1,
            "arcs": [
                {
                    "arc_number": 1,
                    "name": "An arc",
                    "slug": "a-slug",
                    "file_path": "a.py",
                    "commits": [],
                    "commit_count": 0,
                    "datable_count": 0,
                }
            ],
        },
        "file_lifespans": [],
        "files": [],
        "generated_at": "2026-06-18",
    }
    html = render_broadsheet(data)
    assert f'data-arc-color="{NEON_ARC_COLORS[0]}"' in html  # first arc → first neon
    assert "transform: scale" in html  # the grow
    assert "data-arc-color" in html  # the script reads it (see below)

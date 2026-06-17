"""Tests for the packed density-timeline rendering of named arcs (#112).

The lane-packing math is proven in test_arc_layout.py; here we assert the SVG
shell wires it in: one lozenge per datable arc, registered to the shared spine,
plus a folded full-arc list that prints expanded.
"""

from __future__ import annotations

from antiquarian.render import render_arc_band

TIMELINE = {
    "full_span": {
        "start": "2020-01-01T00:00:00+00:00",
        "end": "2026-01-01T00:00:00+00:00",
        "days": 2192,
    },
    "active_windows": [],
    "gaps": [],
}


def _arc(
    number: int, start: str, end: str, name: str = "An arc", path: str = "a.py"
) -> dict:
    return {
        "arc_number": number,
        "name": name,
        "file_path": path,
        "commits": [
            {
                "timestamp": f"{start}T00:00:00+00:00",
                "short_sha": "aaa",
                "subject": "s",
            },
            {"timestamp": f"{end}T00:00:00+00:00", "short_sha": "bbb", "subject": "s"},
        ],
    }


def _band(arcs: list[dict]) -> dict:
    return {"arc_count": len(arcs), "arcs": arcs}


def test_one_lozenge_per_datable_arc():
    arcs = [_arc(1, "2021-01-01", "2021-06-01"), _arc(2, "2023-01-01", "2023-03-01")]
    out = render_arc_band(_band(arcs), TIMELINE)
    assert out.count('class="arc-lozenge"') == 2


def test_lozenge_carries_arc_number_dataattr():
    out = render_arc_band(_band([_arc(7, "2022-01-01", "2022-02-01")]), TIMELINE)
    assert 'data-arc="7"' in out


def test_full_arc_list_present_and_lists_every_arc():
    arcs = [
        _arc(1, "2021-01-01", "2021-02-01", name="Alpha"),
        _arc(2, "2022-01-01", "2022-02-01", name="Beta"),
    ]
    out = render_arc_band(_band(arcs), TIMELINE)
    assert 'class="arc-list"' in out
    assert "Alpha" in out and "Beta" in out


def test_non_datable_arc_listed_but_not_drawn():
    nodate = {
        "arc_number": 9,
        "name": "Ghost",
        "file_path": "a.py",
        "commits": [{"timestamp": None, "short_sha": "x", "subject": "s"}],
    }
    out = render_arc_band(_band([nodate]), TIMELINE)
    assert out.count('class="arc-lozenge"') == 0  # nothing on the spine
    assert "Ghost" in out  # but kept in the list (in-DOM rule)


def test_empty_arcs_uses_empty_atom():
    out = render_arc_band(_band([]), TIMELINE)
    assert "No arcs found." in out


def test_uses_swimlane_margins_for_spine_alignment():
    # width must match the swimlane (margin_left 220 + chart_w 760 + margin_right 60)
    out = render_arc_band(_band([_arc(1, "2021-01-01", "2021-06-01")]), TIMELINE)
    assert 'viewBox="0 0 1040 ' in out


# ---------------------------------------------------------------------------
# Page-level print rule
# ---------------------------------------------------------------------------
from antiquarian.render import render_broadsheet  # noqa: E402


def test_arc_list_prints_expanded():
    # minimal data bundle with one arc; render the whole page and check print CSS
    data = {
        "project": "p",
        "timeline": TIMELINE,
        "todos": [],
        "swimlane": {"lanes": []},
        "arc_band": _band([_arc(1, "2021-01-01", "2021-06-01")]),
        "file_lifespans": [],
        "files": [],
        "generated_at": "2026-06-17",
    }
    html = render_broadsheet(data)
    assert "@media print" in html
    assert ".arc-list" in html

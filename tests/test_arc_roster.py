"""Tests for the pure arc-roster grouping (#112 rethink, fixes #133).

An arc is a named SET of commits; the roster groups arcs by file and counts
how many are datable, so the renderer can badge undatable arcs instead of
silently dropping them. No HTML here.
"""

from __future__ import annotations

from antiquarian.arc_roster import (
    FileArcGroup,
    datable_count,
    group_arcs_by_file,
)


def _arc(number, file_path, *, datable=1, undatable=0):
    commits = [
        {"short_sha": f"d{i}", "timestamp": f"2021-0{(i % 9) + 1}-01T00:00:00+00:00"}
        for i in range(datable)
    ]
    commits += [
        {"short_sha": f"m{i}", "timestamp": None, "missing": True}
        for i in range(undatable)
    ]
    return {
        "arc_number": number,
        "name": f"Arc {number}",
        "file_path": file_path,
        "commits": commits,
    }


def test_datable_count_counts_only_timestamped():
    assert datable_count(_arc(1, "a.py", datable=3, undatable=2)) == 3
    assert datable_count(_arc(2, "a.py", datable=0, undatable=4)) == 0


def test_groups_by_file_sorted():
    groups = group_arcs_by_file([_arc(1, "z.py"), _arc(2, "a.py"), _arc(3, "a.py")])
    assert [g.file_path for g in groups] == ["a.py", "z.py"]
    assert isinstance(groups[0], FileArcGroup)
    assert [a["arc_number"] for a in groups[0].arcs] == [2, 3]


def test_group_counts():
    groups = group_arcs_by_file(
        [
            _arc(1, "a.py", datable=2),
            _arc(2, "a.py", datable=0, undatable=3),  # undatable
            _arc(3, "a.py", datable=1),
        ]
    )
    g = groups[0]
    assert g.arc_count == 3
    assert g.datable_arc_count == 2  # arc 2 is undatable


def test_empty():
    assert group_arcs_by_file([]) == []

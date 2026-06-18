"""Pure grouping for the honest arc roster (#112 rethink; fixes #133).

An arc is a named SET of commits at synthesis confidence — not a time span.
This module groups arcs by file and counts datable commits so the renderer can
list every arc and badge undatable ones instead of dropping them. No HTML, no IO.
See docs/superpowers/specs/2026-06-17-arcs-as-commit-sets-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass


def datable_count(arc: dict) -> int:
    """Number of the arc's commits that carry a real (truthy) timestamp."""
    return sum(1 for c in arc["commits"] if c.get("timestamp"))


@dataclass(frozen=True)
class FileArcGroup:
    """All arcs named in one file, with datable/total counts."""

    file_path: str
    arcs: list
    arc_count: int
    datable_arc_count: int


def group_arcs_by_file(arcs: list[dict]) -> list[FileArcGroup]:
    """Group arcs by ``file_path``; arcs sorted by number, groups by path."""
    by_file: dict[str, list[dict]] = {}
    for arc in arcs:
        by_file.setdefault(arc["file_path"], []).append(arc)

    groups: list[FileArcGroup] = []
    for file_path in sorted(by_file):
        file_arcs = sorted(by_file[file_path], key=lambda a: a["arc_number"])
        datable = sum(1 for a in file_arcs if datable_count(a) > 0)
        groups.append(
            FileArcGroup(
                file_path=file_path,
                arcs=file_arcs,
                arc_count=len(file_arcs),
                datable_arc_count=datable,
            )
        )
    return groups

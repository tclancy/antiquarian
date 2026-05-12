"""Pull real per-file stories + cache.db rows for a project, emit JSON specs.

The playground is feel-testing infrastructure, not a finished product. This script
is the single source of truth for what each of the three viz stacks renders. The
Python pipeline owns the data shape; the stacks just paint it. Derive-don't-duplicate.

Usage:
    python extract.py --project itguy --repo /Users/tom/Documents/work/itguy

Outputs JSON files into output/<project>/data/:
    - commits.json        — flat commit list (for swimlane + SC band)
    - todos.json          — current TODOs per file (for TODO-age strip)
    - arcs.json           — Major arcs parsed from each per-file story
    - manifest.json       — list of files, projects, and which atoms have data

Honest data only: if a file has no TODOs, the JSON reflects that. If a project
has no story, the arcs.json reflects that. The playground surfaces these gaps
rather than papering over them — per the project's "lossy regions are signal"
ethos.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Make the antiquarian package importable when running from the playground.
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from antiquarian.todos import extract_todos  # noqa: E402


# Arc-name → short tag. Stories use freeform names like "Arc 1 — Strategy proliferation"
# so we hash to a slug for stable color assignment downstream.
_ARC_HEADING_RE = re.compile(r"^\*\*Arc\s+(\d+)\s*[—-]\s*(.+?)\.\*\*\s*(.*)", re.DOTALL)
# Match commit SHAs referenced in arc body (8-40 hex chars in backticks)
_SHA_REF_RE = re.compile(r"`([0-9a-f]{7,40})`")
# Match dates inside parentheses at the head of an arc, e.g. "(late March → early April 2026)"
_DATE_RANGE_RE = re.compile(r"\(([^)]+\d{4}[^)]*)\)")


@dataclass
class Commit:
    sha: str
    short_sha: str
    author: str
    author_email: str
    timestamp: str  # ISO-8601
    date: str  # YYYY-MM-DD
    message_subject: str
    additions: int
    deletions: int
    files_changed_count: int
    pr_number: int | None
    arcs: list[str] = field(default_factory=list)  # which arc slugs reference this sha


@dataclass
class Todo:
    file_path: str
    kind: str
    line_number: int
    text: str
    introduced_sha: str
    introduced_short: str
    introduced_at: str
    introduced_by: str
    age_days: int


@dataclass
class Arc:
    file_path: str
    arc_number: int
    name: str
    slug: str
    date_range: str | None
    body: str
    commit_shas: list[str]  # full or short shas referenced in this arc's body


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
    return s[:40]


def load_commits(cache_db: Path, file_filter: list[str] | None = None) -> list[Commit]:
    if not cache_db.exists():
        return []
    conn = sqlite3.connect(str(cache_db))
    conn.row_factory = sqlite3.Row
    try:
        if file_filter:
            placeholders = ",".join("?" for _ in file_filter)
            rows = conn.execute(
                f"SELECT * FROM commit_features WHERE file_path IN ({placeholders})",
                file_filter,
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM commit_features").fetchall()
    finally:
        conn.close()

    commits: list[Commit] = []
    for row in rows:
        msg = row["message"] or ""
        subject = msg.splitlines()[0] if msg else ""
        # Truncate long subjects so the JSON stays render-friendly.
        if len(subject) > 120:
            subject = subject[:117] + "..."
        files_changed = json.loads(row["files_changed"]) if row["files_changed"] else []
        commits.append(
            Commit(
                sha=row["sha"],
                short_sha=row["sha"][:8],
                author=row["author"],
                author_email=row["author_email"],
                timestamp=row["timestamp"],
                date=row["timestamp"][:10],
                message_subject=subject,
                additions=row["additions"],
                deletions=row["deletions"],
                files_changed_count=len(files_changed),
                pr_number=row["pr_number"],
            )
        )
    # Deduplicate (sha may appear twice if the same file was mined with different
    # filter perspectives). Newest wins.
    by_sha: dict[str, Commit] = {}
    for c in commits:
        by_sha[c.sha] = c
    return sorted(by_sha.values(), key=lambda c: c.timestamp)


def parse_arcs(story_md: Path) -> list[Arc]:
    """Pull the Major arcs section out of a per-file story.

    Stories produced by `antiquarian story` follow a fixed structure with
    `## Major arcs` as a heading and `**Arc N — Name.**` paragraphs underneath.
    We slice that section, then split on the bold arc headers.
    """
    text = story_md.read_text(encoding="utf-8")
    # Slice the major arcs section.
    arcs_match = re.search(
        r"^##\s+Major arcs\s*\n(.+?)(?=^##\s+\w|\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not arcs_match:
        return []
    section = arcs_match.group(1)

    # Convert the stories' relative path notation `src__itguy__deploy.py.md` back
    # to its file path equivalent for downstream linking.
    file_path = story_md.stem.replace("__", "/")

    # Split on `**Arc N —` boundaries. Keep the leading **.
    parts = re.split(r"\n(?=\*\*Arc\s+\d+\s*[—-])", section)
    arcs: list[Arc] = []
    for part in parts:
        part = part.strip()
        if not part.startswith("**Arc"):
            continue
        m = _ARC_HEADING_RE.match(part)
        if not m:
            continue
        arc_num = int(m.group(1))
        rest = m.group(2)  # "Strategy proliferation (late March → ...)"
        body = m.group(3).strip()
        # Extract date range if present.
        dr_match = _DATE_RANGE_RE.search(rest)
        date_range = dr_match.group(1).strip() if dr_match else None
        name = _DATE_RANGE_RE.sub("", rest).strip()
        slug = _slugify(name)
        commit_shas = list(
            dict.fromkeys(_SHA_REF_RE.findall(part))
        )  # dedup, preserve order
        arcs.append(
            Arc(
                file_path=file_path,
                arc_number=arc_num,
                name=name,
                slug=slug,
                date_range=date_range,
                body=body,
                commit_shas=commit_shas,
            )
        )
    return arcs


def attach_arcs_to_commits(commits: list[Commit], arcs: list[Arc]) -> None:
    """Mark each commit with the arc(s) that reference it.

    Stories reference commits by short or partial SHA in backticks. We match by
    prefix so 8-char and 7-char references both connect.
    """
    by_sha = {c.sha: c for c in commits}
    by_short = {c.sha[:8]: c for c in commits}
    by_seven = {c.sha[:7]: c for c in commits}
    for arc in arcs:
        for ref in arc.commit_shas:
            commit = by_sha.get(ref) or by_short.get(ref[:8]) or by_seven.get(ref[:7])
            if commit and arc.slug not in commit.arcs:
                commit.arcs.append(arc.slug)


def load_todos(repo_path: Path, files: list[str]) -> list[Todo]:
    """Run extract_todos against the repo for the listed files.

    Real TODOs from the live HEAD checkout. Files without TODOs simply produce
    no rows — the absence is itself the signal.
    """
    todos: list[Todo] = []
    for f in files:
        for t in extract_todos(repo_path, f):
            todos.append(
                Todo(
                    file_path=f,
                    kind=t.kind,
                    line_number=t.line_number,
                    text=t.text,
                    introduced_sha=t.introduced_commit,
                    introduced_short=t.introduced_commit[:8],
                    introduced_at=t.introduced_at.isoformat(),
                    introduced_by=t.introduced_by,
                    age_days=t.age_days,
                )
            )
    # Sort by introduced_at ascending so visual bars line up chronologically.
    todos.sort(key=lambda t: t.introduced_at)
    return todos


def build_swimlane(commits: list[Commit]) -> dict:
    """Compute aggregate swimlane data (one row per author, time on X, marks per commit).

    Author email is sticky — same person can show two different display names
    over time. We group by email but display the most recent name.
    """
    by_email: dict[str, dict] = defaultdict(
        lambda: {"author": "", "email": "", "commits": []}
    )
    for c in commits:
        bucket = by_email[c.author_email]
        bucket["email"] = c.author_email
        bucket["author"] = c.author  # last name wins; commits are time-sorted
        bucket["commits"].append(
            {
                "sha": c.sha,
                "short_sha": c.short_sha,
                "timestamp": c.timestamp,
                "date": c.date,
                "additions": c.additions,
                "deletions": c.deletions,
                "subject": c.message_subject,
                "arcs": c.arcs,
            }
        )
    lanes = []
    for bucket in by_email.values():
        lanes.append(
            {
                "author": bucket["author"],
                "email": bucket["email"],
                "commit_count": len(bucket["commits"]),
                "first_commit": min(c["timestamp"] for c in bucket["commits"]),
                "last_commit": max(c["timestamp"] for c in bucket["commits"]),
                "commits": bucket["commits"],
            }
        )
    # Sort lanes by first-commit ascending — earliest contributor on top.
    lanes.sort(key=lambda lane: lane["first_commit"])
    return {
        "lane_count": len(lanes),
        "lanes": lanes,
        "time_min": min((c.timestamp for c in commits), default=None),
        "time_max": max((c.timestamp for c in commits), default=None),
    }


def build_arc_band(arcs: list[Arc], commits: list[Commit]) -> dict:
    """Build per-arc SC ranking band data.

    For each arc, list the commits attached to it in chronological order, with
    the decisive ones (those explicitly referenced in the arc body) marked.
    Currently every arc-attached commit IS a decisive one — the story only
    namechecks the load-bearing SHAs. We keep the field explicit so a future
    SC-scoring pass can demote non-decisive supporting commits.
    """
    by_sha = {c.sha: c for c in commits}
    by_short = {c.sha[:8]: c for c in commits}
    by_seven = {c.sha[:7]: c for c in commits}
    bands = []
    for arc in arcs:
        arc_commits = []
        for ref in arc.commit_shas:
            commit = by_sha.get(ref) or by_short.get(ref[:8]) or by_seven.get(ref[:7])
            if commit is None:
                # The arc references a SHA we don't have features for — that's
                # a real gap in the cache. Mark it explicitly rather than drop.
                arc_commits.append(
                    {
                        "sha": ref,
                        "short_sha": ref[:8],
                        "timestamp": None,
                        "date": None,
                        "subject": "(commit not in cache)",
                        "decisive": True,
                        "missing": True,
                    }
                )
                continue
            arc_commits.append(
                {
                    "sha": commit.sha,
                    "short_sha": commit.short_sha,
                    "timestamp": commit.timestamp,
                    "date": commit.date,
                    "subject": commit.message_subject,
                    "decisive": True,
                    "missing": False,
                }
            )
        # Sort by timestamp where we have it; nulls last.
        arc_commits.sort(key=lambda c: c["timestamp"] or "9999")
        bands.append(
            {
                "arc_number": arc.arc_number,
                "name": arc.name,
                "slug": arc.slug,
                "date_range": arc.date_range,
                "file_path": arc.file_path,
                "commits": arc_commits,
                "commit_count": len(arc_commits),
            }
        )
    return {
        "arc_count": len(bands),
        "arcs": bands,
    }


def discover_stories(repo_path: Path) -> list[Path]:
    """Return all story markdowns living under .antiquarian/stories/."""
    stories_dir = repo_path / ".antiquarian" / "stories"
    if not stories_dir.exists():
        return []
    return sorted(stories_dir.glob("*.md"))


def discover_files_in_cache(cache_db: Path) -> list[str]:
    if not cache_db.exists():
        return []
    conn = sqlite3.connect(str(cache_db))
    try:
        rows = conn.execute("SELECT DISTINCT file_path FROM commit_features").fetchall()
    finally:
        conn.close()
    return sorted(r[0] for r in rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--project", required=True, help="Project name (used for output dir)."
    )
    ap.add_argument(
        "--repo", required=True, type=Path, help="Path to the project's repo."
    )
    ap.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "output",
        help="Output directory root (default: viz-playground/output/).",
    )
    args = ap.parse_args()

    repo_path: Path = args.repo.resolve()
    cache_db = repo_path / ".antiquarian" / "cache.db"
    project_out = args.output_root / args.project / "data"
    project_out.mkdir(parents=True, exist_ok=True)

    cached_files = discover_files_in_cache(cache_db)
    stories = discover_stories(repo_path)

    print(f"[extract] project={args.project} repo={repo_path}", file=sys.stderr)
    print(f"[extract] cache.db files: {len(cached_files)}", file=sys.stderr)
    print(f"[extract] stories: {len(stories)}", file=sys.stderr)

    commits = load_commits(cache_db, file_filter=cached_files or None)
    arcs: list[Arc] = []
    for story_path in stories:
        arcs.extend(parse_arcs(story_path))
    attach_arcs_to_commits(commits, arcs)
    todos = load_todos(repo_path, cached_files)

    swimlane = build_swimlane(commits)
    arc_band = build_arc_band(arcs, commits)

    # Emit each atom's data as a separate JSON file so the stacks can load only
    # what they need.
    (project_out / "commits.json").write_text(
        json.dumps([asdict(c) for c in commits], indent=2), encoding="utf-8"
    )
    (project_out / "todos.json").write_text(
        json.dumps([asdict(t) for t in todos], indent=2), encoding="utf-8"
    )
    (project_out / "arcs.json").write_text(
        json.dumps([asdict(a) for a in arcs], indent=2), encoding="utf-8"
    )
    (project_out / "swimlane.json").write_text(
        json.dumps(swimlane, indent=2), encoding="utf-8"
    )
    (project_out / "arc_band.json").write_text(
        json.dumps(arc_band, indent=2), encoding="utf-8"
    )

    manifest = {
        "project": args.project,
        "repo_path": str(repo_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": cached_files,
        "stories": [s.name for s in stories],
        "atoms": {
            "swimlane": {
                "data": "swimlane.json",
                "lane_count": swimlane["lane_count"],
                "commit_count": len(commits),
            },
            "todo_strip": {
                "data": "todos.json",
                "todo_count": len(todos),
            },
            "arc_band": {
                "data": "arc_band.json",
                "arc_count": arc_band["arc_count"],
            },
        },
    }
    (project_out / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    print(
        f"[extract] wrote {len(commits)} commits, {len(todos)} todos, {len(arcs)} arcs "
        f"to {project_out}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

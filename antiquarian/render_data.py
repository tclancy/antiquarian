"""Pull per-file stories + cache.db rows into a single dict ready for rendering.

This is the data-extraction half of the broadsheet renderer (issue #40 — promoted
out of ``viz-playground/data/extract.py``). The library entry point is
``extract_render_data(repo_path) -> dict``. The CLI's ``antiquarian render``
command consumes the dict and passes it to ``antiquarian.render.render_broadsheet``.

Honest data only: if a file has no TODOs, the dict reflects that. If a project
has no story, the arcs are empty. The renderer surfaces those gaps rather than
papering over them — per the "lossy regions are signal" ethos.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from antiquarian.cache import cache_path_for_repo
from antiquarian.todos import extract_todos

# Arc-name → short tag. Stories use freeform names like "Arc 1 — Strategy
# proliferation" so we hash to a slug for stable color assignment downstream.
_ARC_HEADING_RE = re.compile(r"^\*\*Arc\s+(\d+)\s*[—-]\s*(.+?)\.\*\*\s*(.*)", re.DOTALL)
# Match commit SHAs referenced in arc body (8-40 hex chars in backticks)
_SHA_REF_RE = re.compile(r"`([0-9a-f]{7,40})`")
# Match dates inside parentheses at the head of an arc, e.g. "(late March → early April 2026)"
_DATE_RANGE_RE = re.compile(r"\(([^)]+\d{4}[^)]*)\)")

# A gap of >= this many days between consecutive commits breaks the active-window
# timeline into separate windows. Calibrated against comictagger (multi-year
# SVN-to-Git gaps) — long enough to capture real dormancy without splitting on
# every short vacation.
_TIMELINE_GAP_THRESHOLD_DAYS = 365


@dataclass
class _Commit:
    sha: str
    short_sha: str
    author: str
    author_email: str
    timestamp: str
    date: str
    message_subject: str
    additions: int
    deletions: int
    files_changed_count: int
    pr_number: int | None
    arcs: list[str] = field(default_factory=list)


@dataclass
class _Todo:
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
class _Arc:
    file_path: str
    arc_number: int
    name: str
    slug: str
    date_range: str | None
    body: str
    commit_shas: list[str]


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
    return s[:40]


def _load_commits(
    cache_db: Path, file_filter: list[str] | None = None
) -> list[_Commit]:
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

    commits: list[_Commit] = []
    for row in rows:
        msg = row["message"] or ""
        subject = msg.splitlines()[0] if msg else ""
        if len(subject) > 120:
            subject = subject[:117] + "..."
        files_changed = json.loads(row["files_changed"]) if row["files_changed"] else []
        commits.append(
            _Commit(
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
    # Deduplicate (the same SHA may appear under different file_path rows).
    by_sha: dict[str, _Commit] = {}
    for c in commits:
        by_sha[c.sha] = c
    return sorted(by_sha.values(), key=lambda c: c.timestamp)


def _parse_arcs(story_md: Path) -> list[_Arc]:
    """Pull the Major arcs section out of a per-file story.

    Stories follow a fixed structure with ``## Major arcs`` as a heading and
    ``**Arc N — Name.**`` paragraphs underneath.
    """
    text = story_md.read_text(encoding="utf-8")
    arcs_match = re.search(
        r"^##\s+Major arcs\s*\n(.+?)(?=^##\s+\w|\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not arcs_match:
        return []
    section = arcs_match.group(1)
    file_path = story_md.stem.replace("__", "/")

    parts = re.split(r"\n(?=\*\*Arc\s+\d+\s*[—-])", section)
    arcs: list[_Arc] = []
    for part in parts:
        part = part.strip()
        if not part.startswith("**Arc"):
            continue
        m = _ARC_HEADING_RE.match(part)
        if not m:
            continue
        arc_num = int(m.group(1))
        rest = m.group(2)
        body = m.group(3).strip()
        dr_match = _DATE_RANGE_RE.search(rest)
        date_range = dr_match.group(1).strip() if dr_match else None
        name = _DATE_RANGE_RE.sub("", rest).strip()
        slug = _slugify(name)
        commit_shas = list(dict.fromkeys(_SHA_REF_RE.findall(part)))
        arcs.append(
            _Arc(
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


def _attach_arcs_to_commits(commits: list[_Commit], arcs: list[_Arc]) -> None:
    """Mark each commit with the arc(s) that reference it.

    Stories reference commits by short or partial SHA in backticks. Match by
    prefix so 7-char and 8-char references both connect.
    """
    by_sha = {c.sha: c for c in commits}
    by_short = {c.sha[:8]: c for c in commits}
    by_seven = {c.sha[:7]: c for c in commits}
    for arc in arcs:
        for ref in arc.commit_shas:
            commit = by_sha.get(ref) or by_short.get(ref[:8]) or by_seven.get(ref[:7])
            if commit and arc.slug not in commit.arcs:
                commit.arcs.append(arc.slug)


def _load_todos(repo_path: Path, files: list[str]) -> list[_Todo]:
    todos: list[_Todo] = []
    for f in files:
        for t in extract_todos(repo_path, f):
            todos.append(
                _Todo(
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
    todos.sort(key=lambda t: t.introduced_at)
    return todos


def _build_swimlane(commits: list[_Commit]) -> dict:
    """One row per author, time on X, marks per commit.

    Author email is sticky — same person can show two different display names
    over time. Group by email but display the most recent name.
    """
    by_email: dict[str, dict] = defaultdict(
        lambda: {"author": "", "email": "", "commits": []}
    )
    for c in commits:
        bucket = by_email[c.author_email]
        bucket["email"] = c.author_email
        bucket["author"] = c.author
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
                "total_loc": sum(
                    c["additions"] + c["deletions"] for c in bucket["commits"]
                ),
                "first_commit": min(c["timestamp"] for c in bucket["commits"]),
                "last_commit": max(c["timestamp"] for c in bucket["commits"]),
                "commits": bucket["commits"],
            }
        )
    # Rank by contribution so the eye can compare: most commits first, total LoC
    # as the tiebreak, email last for a stable order (#118).
    lanes.sort(
        key=lambda lane: (-lane["commit_count"], -lane["total_loc"], lane["email"])
    )
    return {
        "lane_count": len(lanes),
        "lanes": lanes,
        "time_min": min((c.timestamp for c in commits), default=None),
        "time_max": max((c.timestamp for c in commits), default=None),
    }


def _build_timeline(commits: list[_Commit]) -> dict:
    """Dual-axis timeline metadata: full lifespan + active windows.

    Two ranges:
      - ``full_span``: project lifespan (cache min → cache max). The thin
        reference strip at the top of each atom shows this.
      - ``active_windows``: contiguous commit clusters; gaps larger than
        ``_TIMELINE_GAP_THRESHOLD_DAYS`` collapse into separate windows. The
        visualized axis shows only the union of these windows with explicit
        "gap" segments between them so dormancy stays structurally visible.

    Why: comictagger spans 2013-02 → 2022-11 with two big gaps. A naive time
    axis renders 99% empty space. A pure-active-window axis hides the
    dormancy. The dual-axis approach is honest about both.
    """
    if not commits:
        return {
            "full_span": None,
            "active_windows": [],
            "gaps": [],
            "active_total_days": 0,
            "compression_ratio": 1.0,
        }
    sorted_commits = sorted(commits, key=lambda c: c.timestamp)
    timestamps = [c.timestamp for c in sorted_commits]
    full_min = timestamps[0]
    full_max = timestamps[-1]

    def _parse(ts: str) -> datetime:
        return datetime.fromisoformat(ts)

    windows: list[dict] = []
    gaps: list[dict] = []
    cur_start = timestamps[0]
    cur_end = timestamps[0]
    cur_count = 1
    for i in range(1, len(sorted_commits)):
        prev = _parse(timestamps[i - 1])
        cur = _parse(timestamps[i])
        delta_days = (cur - prev).days
        if delta_days >= _TIMELINE_GAP_THRESHOLD_DAYS:
            windows.append(
                {"start": cur_start, "end": cur_end, "commit_count": cur_count}
            )
            gaps.append(
                {
                    "start": timestamps[i - 1],
                    "end": timestamps[i],
                    "days": delta_days,
                }
            )
            cur_start = timestamps[i]
            cur_count = 0
        cur_end = timestamps[i]
        cur_count += 1
    windows.append({"start": cur_start, "end": cur_end, "commit_count": cur_count})

    active_total_days = sum(
        (_parse(w["end"]) - _parse(w["start"])).days + 1 for w in windows
    )
    full_total_days = (_parse(full_max) - _parse(full_min)).days + 1
    return {
        "full_span": {"start": full_min, "end": full_max, "days": full_total_days},
        "active_windows": windows,
        "active_total_days": active_total_days,
        "gaps": gaps,
        "compression_ratio": (
            full_total_days / active_total_days if active_total_days else 1.0
        ),
    }


def _build_per_file_lifespans(
    cache_db: Path, files: list[str], commits: list[_Commit]
) -> list[dict]:
    """Per-file first/last commit + commit count.

    Detects ``git log --follow`` rename truncation: a file with one commit on a
    date > 1 year before any other surviving evidence is almost certainly a
    rename boundary where pre-rename history dropped off. The renderer surfaces
    this as a "history truncated at rename" indicator rather than papering over.
    """
    if not cache_db.exists():
        return []
    conn = sqlite3.connect(str(cache_db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT file_path, MIN(timestamp) as first_ts, MAX(timestamp) as last_ts, "
            "COUNT(*) as n FROM commit_features GROUP BY file_path"
        ).fetchall()
    finally:
        conn.close()
    out = []
    all_firsts = sorted(r["first_ts"] for r in rows)
    for r in rows:
        first = datetime.fromisoformat(r["first_ts"])
        likely_truncated = False
        if r["n"] == 1 and len(all_firsts) > 1:
            others = [
                datetime.fromisoformat(t) for t in all_firsts if t != r["first_ts"]
            ]
            if others and (min(others) - first).days > _TIMELINE_GAP_THRESHOLD_DAYS:
                likely_truncated = True
        out.append(
            {
                "file_path": r["file_path"],
                "first_commit": r["first_ts"],
                "last_commit": r["last_ts"],
                "commit_count": r["n"],
                "likely_rename_truncated": likely_truncated,
            }
        )
    out.sort(key=lambda f: f["first_commit"])
    return out


def _build_arc_band(arcs: list[_Arc], commits: list[_Commit]) -> dict:
    """Per-arc commit ranking.

    For each arc, list the commits attached to it chronologically. Decisive
    ones (explicitly referenced in the arc body) are marked. Currently every
    arc-attached commit is decisive; the field stays explicit so a future
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
                # Arc references a SHA we don't have features for — real cache
                # gap. Mark explicitly rather than drop.
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
    return {"arc_count": len(bands), "arcs": bands}


def _discover_stories(repo_path: Path) -> list[Path]:
    stories_dir = repo_path / ".antiquarian" / "stories"
    if not stories_dir.exists():
        return []
    return sorted(stories_dir.glob("*.md"))


def _discover_files_in_cache(cache_db: Path) -> list[str]:
    if not cache_db.exists():
        return []
    conn = sqlite3.connect(str(cache_db))
    try:
        rows = conn.execute("SELECT DISTINCT file_path FROM commit_features").fetchall()
    finally:
        conn.close()
    return sorted(r[0] for r in rows)


_ORIGIN_RE = re.compile(r"##\s+Origin\s*\n+(.*?)(?:\n\n|\Z)", re.DOTALL)
_FIRST_SENTENCE_RE = re.compile(r"^(.+?\.)\s", re.DOTALL)


def _extract_story_descriptions(stories: list[Path]) -> dict[str, str]:
    """Extract a one-sentence description from each story's Origin section.

    Returns ``{file_path: description}`` where ``file_path`` is the repo-
    relative path (e.g. ``src/a.py``) derived from the story filename
    (``src__a.py.md`` → ``src/a.py``).
    """
    descriptions: dict[str, str] = {}
    for story_path in stories:
        text = story_path.read_text(encoding="utf-8", errors="replace")
        m = _ORIGIN_RE.search(text)
        if not m:
            continue
        para = m.group(1).strip()
        sent_m = _FIRST_SENTENCE_RE.match(para)
        sentence = sent_m.group(1) if sent_m else para
        sentence = re.sub(r"`[^`]+`", "", sentence).strip()
        if len(sentence) > 120:
            sentence = sentence[:115].rsplit(" ", 1)[0] + "…"
        file_path = story_path.stem.replace("__", "/")
        descriptions[file_path] = sentence
    return descriptions


def _pull_survey_excerpt(repo_path: Path) -> str | None:
    """First arc paragraph from the most recent survey's Cross-file arcs section.

    The renderer uses this as a pull-quote in the broadsheet header. We target
    the cross-file arcs specifically because that's the most narratively
    interesting prose in any survey output — an arc paragraph distills the
    "this is what happened" beat across multiple files.

    Returns None if there's no surveys/ dir, no survey file, or the regex
    doesn't match (the survey came back in a different shape). Truncates at
    ~480 chars at the nearest word boundary so the renderer doesn't have to
    worry about pull-quote overflow.
    """
    surveys_dir = repo_path / ".antiquarian" / "surveys"
    if not surveys_dir.exists():
        return None
    survey_files = sorted(surveys_dir.glob("*.md"))
    if not survey_files:
        return None
    text = survey_files[-1].read_text(encoding="utf-8", errors="replace")
    m = re.search(
        r"##\s+Cross-file arcs\s*\n+(\*\*Arc\s+\w+\s*[—-][^\n]+\.\*\*[^\n]+)",
        text,
    )
    if not m:
        return None
    body = m.group(1)
    if len(body) > 480:
        body = body[:475].rsplit(" ", 1)[0] + "…"
    return body


def _pull_dramatis_personae(repo_path: Path) -> list[dict[str, str]]:
    """Extract Dramatis Personae entries from the most recent survey.

    Returns a list of dicts with ``name`` and ``description`` keys, one per
    contributor. Returns an empty list when the survey has no Dramatis Personae
    section or no survey exists.

    Format expected in the survey markdown::

        ## Dramatis Personae

        **`Author Name`** — Description sentence(s).
    """
    surveys_dir = repo_path / ".antiquarian" / "surveys"
    if not surveys_dir.exists():
        return []
    survey_files = sorted(surveys_dir.glob("*.md"))
    if not survey_files:
        return []
    text = survey_files[-1].read_text(encoding="utf-8", errors="replace")
    m = re.search(
        r"##\s+Dramatis Personae\s*\n+([\s\S]+?)(?=\n##\s|\Z)",
        text,
    )
    if not m:
        return []
    entries: list[dict[str, str]] = []
    for entry_m in re.finditer(
        r"\*\*`?([^`*]+?)`?\*\*\s*[—–-]\s*(.+?)(?=\n\n\*\*|\n\n##|\Z)",
        m.group(1),
        re.DOTALL,
    ):
        name = entry_m.group(1).strip()
        desc = entry_m.group(2).strip()
        if len(desc) > 300:
            desc = desc[:295].rsplit(" ", 1)[0] + "…"
        entries.append({"name": name, "description": desc})
    return entries


def extract_render_data(repo_path: Path) -> dict:
    """Pull the cache.db + stories into a single dict ready for rendering.

    Returns a dict with the atoms the broadsheet renderer consumes:

    - ``project``: repo directory name (used for the masthead)
    - ``repo_path``: absolute path, for the renderer's pull-quote lookup
    - ``generated_at``: ISO-8601 timestamp
    - ``files``: sorted list of file paths in the cache
    - ``commits``: deduplicated, chronologically sorted commit list
    - ``todos``: TODO/FIXME annotations from the live HEAD
    - ``arcs``: Major-arc paragraphs parsed out of per-file stories
    - ``swimlane``: per-author lanes with commits attached
    - ``arc_band``: per-arc commit groupings
    - ``timeline``: dual-axis (full_span + active_windows + gaps)
    - ``file_lifespans``: per-file first/last/count + rename-truncation flag
    - ``survey_excerpt``: pull-quote from the most recent survey, if any
    - ``dramatis_personae``: contributor entries from the survey, if any
    - ``story_descriptions``: one-sentence Origin excerpts keyed by file path

    All fields are JSON-serializable; the dict can be persisted as JSON for
    caching or inspection.
    """
    repo_path = repo_path.resolve()
    cache_db = cache_path_for_repo(repo_path)

    files = _discover_files_in_cache(cache_db)
    stories = _discover_stories(repo_path)

    commits = _load_commits(cache_db, file_filter=files or None)
    arcs: list[_Arc] = []
    for story_path in stories:
        arcs.extend(_parse_arcs(story_path))
    _attach_arcs_to_commits(commits, arcs)
    todos = _load_todos(repo_path, files)

    return {
        "project": repo_path.name,
        "repo_path": str(repo_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
        "stories": [s.name for s in stories],
        "commits": [asdict(c) for c in commits],
        "todos": [asdict(t) for t in todos],
        "arcs": [asdict(a) for a in arcs],
        "swimlane": _build_swimlane(commits),
        "arc_band": _build_arc_band(arcs, commits),
        "timeline": _build_timeline(commits),
        "file_lifespans": _build_per_file_lifespans(cache_db, files, commits),
        "survey_excerpt": _pull_survey_excerpt(repo_path),
        "dramatis_personae": _pull_dramatis_personae(repo_path),
        "story_descriptions": _extract_story_descriptions(stories),
    }

"""Per-file traffic-light metrics (#148).

Each metric reduces to a 🚦 pip the reader can scan at the top of a story
page. The connecting thread: every metric (a) derives from data the cache
already has, (b) reduces to one of {``green``, ``yellow``, ``red``, ``na``},
and (c) prints with the raw number alongside so paper output doesn't lose
information.

First pass implements three pips that need no language back-end:

- **Bus factor** 🚌 — distinct authors with ≥10% of the file's commits.
  The threshold rubric branches on repo-wide author count (Tom's call on
  #148): repos with one author always get ``na`` here, because a solo-author
  bus-factor pip lights red on every file by construction and stops being
  signal.
- **Churn rate** 🌪️ — commits per year over the file's lifespan.
- **Recency** ⌛ — months since the file's last commit, measured against
  the repo's most recent commit (not wall-clock), so re-rendering the same
  cache is reproducible.

TODO/FIXME and cyclomatic-complexity pips are deferred to a follow-up that
depends on #150 (language-agnostic back-end).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

# Bus-factor rubric — distinct authors with ≥ this share of a file's commits
# count toward the factor. 10% is the cut used in published bus-factor work
# (Avelino et al., "A novel approach for estimating Truck Factors"); above it
# we believe a contributor really carries weight, below it the contact was
# incidental.
BUS_FACTOR_SHARE_THRESHOLD = 0.10

# Cap below which the project doesn't have enough contributors for the pip
# to mean anything. Tom's rubric on #148: solo-author repos get ``na`` rather
# than always-red.
MIN_REPO_AUTHORS_FOR_BUS_PIP = 2


@dataclass(frozen=True)
class Metric:
    """One traffic-light pip's worth of information.

    ``value`` is the raw number behind the pip (None for ``na``). ``level``
    is one of ``green`` / ``yellow`` / ``red`` / ``na`` and drives both the
    swatch colour and the screen-reader label. ``display`` is the rendered
    number (e.g. ``"3"``, ``"7.2/yr"``, ``"14 mo"``).
    """

    glyph: str
    name: str
    level: str
    value: float | None
    display: str
    detail: str  # tooltip / aria-label text


def count_repo_authors(commits_per_file: dict[str, list[dict]]) -> int:
    """Distinct authors across the whole repo's coalesced commit features.

    Counts distinct ``author_email`` values (already coalesced upstream by
    ``.mailmap`` + same-email-name fold) across every commit row regardless
    of file. The result drives the bus-factor pip's repo-wide rubric branch.
    """
    emails: set[str] = set()
    for rows in commits_per_file.values():
        for c in rows:
            email = c.get("author_email") or ""
            if email:
                emails.add(email.lower())
    return len(emails)


def bus_factor(file_commits: list[dict], repo_author_count: int) -> Metric:
    """Distinct authors with ≥10% share of the file's commits.

    Returns ``na`` for solo-author repos (Tom's #148 rubric branch). For
    multi-author repos, ≥3 green / 2 yellow / 1 red.
    """
    if not file_commits:
        return Metric(
            glyph="🚌",
            name="bus factor",
            level="na",
            value=None,
            display="—",
            detail="bus factor unavailable: no commits attributed to this file",
        )
    if repo_author_count < MIN_REPO_AUTHORS_FOR_BUS_PIP:
        # Solo-author repo: pip is always 1, which would always be red.
        # Showing the count instead of a traffic-light keeps the figure
        # honest without flagging every file.
        return Metric(
            glyph="🚌",
            name="bus factor",
            level="na",
            value=1.0,
            display="solo",
            detail="bus factor not meaningful: only one author across the repo",
        )

    counts = Counter(c.get("author_email", "").lower() for c in file_commits)
    counts.pop("", None)
    total = sum(counts.values())
    if total == 0:
        return Metric(
            glyph="🚌",
            name="bus factor",
            level="na",
            value=None,
            display="—",
            detail="bus factor unavailable: commits have no author attribution",
        )
    qualifying = sum(
        1 for n in counts.values() if n / total >= BUS_FACTOR_SHARE_THRESHOLD
    )
    # 11+ contributors with exactly equal share each hold <10%, so
    # qualifying could be 0. That case is "very broad ownership," which
    # is the opposite of a bus risk — clamp to a max of 3 (green) via
    # the green branch rather than reporting "0 carriers."
    if qualifying == 0:
        qualifying = max(3, len(counts))
    if qualifying >= 3:
        level = "green"
    elif qualifying == 2:
        level = "yellow"
    else:
        level = "red"
    return Metric(
        glyph="🚌",
        name="bus factor",
        level=level,
        value=float(qualifying),
        display=str(qualifying),
        detail=(
            f"{qualifying} contributor(s) hold ≥10% of this file's "
            f"{total} attributed commit(s)"
        ),
    )


# Files with a measured lifespan shorter than this are reported as ``na``
# rather than papered over with a synthetic divisor. Under a week of distinct
# activity is too narrow a window for a per-year rate to mean anything; we'd
# rather say "not enough history" than show "60/yr" for five commits on one
# afternoon (#148 review feedback).
_CHURN_MIN_SPAN_DAYS = 7


def churn_rate(file_commits: list[dict]) -> Metric:
    """Commits per year averaged over the file's lifespan.

    Strict-less rubric: ``<4`` green / ``<12`` yellow / ``≥12`` red. Files
    with fewer than two commits or a lifespan shorter than
    :data:`_CHURN_MIN_SPAN_DAYS` get ``na`` because there's no honest rate
    to compute.
    """
    if len(file_commits) < 2:
        return Metric(
            glyph="🌪️",
            name="churn",
            level="na",
            value=None,
            display="—",
            detail="churn unavailable: fewer than two commits in cache",
        )
    timestamps = sorted(
        datetime.fromisoformat(c["timestamp"])
        for c in file_commits
        if c.get("timestamp")
    )
    if len(timestamps) < 2:
        return Metric(
            glyph="🌪️",
            name="churn",
            level="na",
            value=None,
            display="—",
            detail="churn unavailable: timestamps missing from commit rows",
        )
    span_days = (timestamps[-1] - timestamps[0]).days
    if span_days < _CHURN_MIN_SPAN_DAYS:
        return Metric(
            glyph="🌪️",
            name="churn",
            level="na",
            value=None,
            display="—",
            detail=(
                f"churn unavailable: lifespan under {_CHURN_MIN_SPAN_DAYS} days "
                "is too narrow for a per-year rate"
            ),
        )
    span_years = span_days / 365.25
    rate = len(timestamps) / span_years
    # Strict-less boundaries so the docstring matches the code: a file
    # commiting exactly 4/yr lands in yellow, not green.
    if rate < 4.0:
        level = "green"
    elif rate < 12.0:
        level = "yellow"
    else:
        level = "red"
    return Metric(
        glyph="🌪️",
        name="churn",
        level=level,
        value=rate,
        display=f"{rate:.1f}/yr",
        detail=(
            f"{len(timestamps)} commit(s) over {span_years:.1f} year(s) of file history"
        ),
    )


def recency(file_commits: list[dict], reference_dt: datetime) -> Metric:
    """Months since the file's last commit, measured against ``reference_dt``.

    <6 green / 6–24 yellow / ≥24 red. ``reference_dt`` is normally the
    repo's most recent commit timestamp — using wall-clock here would make
    re-rendering the same cache non-reproducible.
    """
    if not file_commits:
        return Metric(
            glyph="⌛",
            name="recency",
            level="na",
            value=None,
            display="—",
            detail="recency unavailable: no commits attributed to this file",
        )
    last_ts = max(
        (
            datetime.fromisoformat(c["timestamp"])
            for c in file_commits
            if c.get("timestamp")
        ),
        default=None,
    )
    if last_ts is None:
        return Metric(
            glyph="⌛",
            name="recency",
            level="na",
            value=None,
            display="—",
            detail="recency unavailable: timestamps missing from commit rows",
        )
    months = max(0.0, (reference_dt - last_ts).days / 30.4375)
    # Round once, then classify off the rounded value so the rendered "24
    # mo" can never sit beside a yellow swatch (#148 review feedback).
    # Strict-less boundaries: ``<6`` green / ``<24`` yellow / ``≥24`` red,
    # matching the docstring.
    whole_months = int(round(months))
    if whole_months < 6:
        level = "green"
    elif whole_months < 24:
        level = "yellow"
    else:
        level = "red"
    display = "<1 mo" if months < 1 else f"{whole_months} mo"
    return Metric(
        glyph="⌛",
        name="recency",
        level=level,
        value=months,
        display=display,
        detail=(
            f"last commit was {months:.1f} month(s) "
            "before the repo's most recent commit"
        ),
    )


def build_file_metrics(
    commits_per_file: dict[str, list[dict]],
    reference_dt: datetime,
) -> dict[str, list[Metric]]:
    """Compute the pip strip for every file in one pass.

    Returns a map ``file_path → [bus, churn, recency]`` so the renderer can
    look up by file path without re-walking commits.
    """
    repo_authors = count_repo_authors(commits_per_file)
    out: dict[str, list[Metric]] = {}
    for file_path, file_commits in commits_per_file.items():
        # Files with no attributed commits get an empty pip strip rather
        # than three dash pips — the renderer omits the strip entirely
        # for an empty list (#148 review feedback).
        if not file_commits:
            out[file_path] = []
            continue
        out[file_path] = [
            bus_factor(file_commits, repo_authors),
            churn_rate(file_commits),
            recency(file_commits, reference_dt),
        ]
    return out


def reference_timestamp(commits_per_file: dict[str, list[dict]]) -> datetime | None:
    """Repo-wide most-recent commit timestamp.

    The recency pip is anchored to this rather than wall-clock so the same
    cache always renders the same pip — important for cache-driven
    reproducibility and dogfood diffs.
    """
    latest: datetime | None = None
    for rows in commits_per_file.values():
        for c in rows:
            ts = c.get("timestamp")
            if not ts:
                continue
            dt = datetime.fromisoformat(ts)
            if latest is None or dt > latest:
                latest = dt
    return latest

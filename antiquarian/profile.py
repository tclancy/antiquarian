"""Structural profilers — per-author baselines, region grouping, file co-change."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from itertools import combinations
from math import log, sqrt
from statistics import median

from ulid import ULID

from antiquarian.models import (
    Act,
    AuthorBaseline,
    CoChange,
    CommitFeatures,
    RegionDefinition,
)

_PATH_TOKEN_RE = re.compile(
    r"[/\\]"  # contains a slash
    r"|\.\w{1,6}$"  # ends with a dot + 1-6 word characters (file extension)
)


def _is_path_token(token: str) -> bool:
    return bool(_PATH_TOKEN_RE.search(token))


def _path_word_ratio(messages: list[str]) -> float:
    total_tokens = 0
    path_tokens = 0
    for msg in messages:
        tokens = msg.split()
        total_tokens += len(tokens)
        path_tokens += sum(1 for t in tokens if _is_path_token(t))
    if total_tokens == 0:
        return 0.0
    return path_tokens / total_tokens


def _typical_hours(hours: list[int]) -> tuple[int, int]:
    """IQR of hour_of_day values (Q1, Q3). Hours are from git commit timestamps, not normalized to any timezone."""
    if not hours:
        return (0, 0)
    if len(hours) == 1:
        return (hours[0], hours[0])
    s = sorted(hours)
    q1 = s[len(s) // 4]
    q3 = s[3 * len(s) // 4]
    return (q1, q3)


def _typical_days(days: list[int]) -> tuple[int, ...]:
    """Days of the week where the author commits above a noise threshold."""
    if not days:
        return ()
    counts: dict[int, int] = defaultdict(int)
    for d in days:
        counts[d] += 1
    total = len(days)
    threshold = total / 14.0
    typical = sorted(d for d, c in counts.items() if c > threshold)
    if not typical:
        typical = sorted(counts.keys())
    return tuple(typical)


def _regions_touched(commits: list[CommitFeatures]) -> dict[str, int]:
    """Top-level directory from files_changed as a region stand-in."""
    region_counts: dict[str, int] = defaultdict(int)
    for commit in commits:
        seen_regions: set[str] = set()
        for path in commit.files_changed:
            parts = path.split("/")
            region = parts[0] if len(parts) > 1 else "."
            seen_regions.add(region)
        for region in seen_regions:
            region_counts[region] += 1
    return dict(region_counts)


def _region_for_path(path: str) -> str | None:
    parts = path.split("/")
    if len(parts) > 1:
        return parts[0]
    return None


def _region_diff_size(commit: CommitFeatures, region: str) -> int:
    """Total diff size for files belonging to a region in a commit."""
    region_files = [f for f in commit.files_changed if _region_for_path(f) == region]
    if not region_files:
        return 0
    fraction = len(region_files) / len(commit.files_changed)
    return int((commit.additions + commit.deletions) * fraction)


def _find_notable_evolutions(commits: list[CommitFeatures], region: str) -> list[str]:
    """SHAs of commits whose region-scoped diff size is a statistical outlier.

    "Notable" here means **statistically unusual relative to this region's own
    history**, not "big in absolute terms." A 200-line commit to a region that
    typically sees 5-line changes is notable; that same commit landing on a
    region whose median commit is 500 lines is not.

    The threshold is a one-sided z-score > 2.0 of region-scoped diff size
    (additions + deletions, prorated by the commit's share of files in this
    region — see ``_region_diff_size``). 2.0 is the standard "roughly the
    top 2.3% of a normal distribution" outlier cutoff, chosen because:

    - It's region-relative, so it adapts to each fiefdom's own pace.
    - It's scale-invariant, so it works across both tiny utility regions
      and large product regions in the same repo.
    - It's one-sided — we only flag commits that are unusually *large*,
      not unusually small.

    Returns an empty list when there are fewer than 2 commits (variance is
    undefined) or when every commit has the same region-scoped diff size
    (no variance, nothing to flag).
    """
    if len(commits) < 2:
        return []
    diffs = [_region_diff_size(c, region) for c in commits]
    mean = sum(diffs) / len(diffs)
    variance = sum((d - mean) ** 2 for d in diffs) / (len(diffs) - 1)
    sd = sqrt(variance) if variance > 0 else 0.0
    if sd == 0.0:
        return []
    notable = []
    for commit, diff in zip(commits, diffs):
        z = (diff - mean) / sd
        if z > 2.0:
            sha = commit.git_sha if commit.git_sha else commit.id
            notable.append(sha)
    return notable


def _group_commits_by_region(
    commits: Sequence[CommitFeatures],
) -> dict[str, list[CommitFeatures]]:
    """Map each region to the commits that touched it.

    A commit appears once per region it touched, regardless of how many
    files within that region it changed (the ``seen`` guard deduplicates
    within a single commit). Root-level files have no region and are
    silently skipped.
    """
    by_region: dict[str, list[CommitFeatures]] = defaultdict(list)
    for commit in commits:
        seen: set[str] = set()
        for path in commit.files_changed:
            region = _region_for_path(path)
            if region is not None and region not in seen:
                by_region[region].append(commit)
                seen.add(region)
    return by_region


def build_regions(
    commits: Sequence[CommitFeatures],
) -> list[RegionDefinition]:
    """Cluster commits into regions based on top-level directory grouping.

    Pure function — no I/O, no git subprocess calls.
    """
    if not commits:
        return []

    by_region = _group_commits_by_region(commits)
    if not by_region:
        return []

    results: list[RegionDefinition] = []
    for region, region_commits in by_region.items():
        earliest = min(region_commits, key=lambda c: c.timestamp)
        introduced_in = earliest.git_sha if earliest.git_sha else earliest.id
        notable = _find_notable_evolutions(region_commits, region)

        results.append(
            RegionDefinition(
                name=region,
                path_prefix=f"{region}/",
                introduced_in=introduced_in,
                notable_evolutions=notable,
            )
        )

    results.sort(key=lambda r: len(by_region[r.name]), reverse=True)
    return results


def build_author_baselines(
    commits: Sequence[CommitFeatures],
) -> dict[str, AuthorBaseline]:
    """Aggregate CommitFeatures into per-author baselines.

    Pure function — no I/O, no git subprocess calls.
    """
    if not commits:
        return {}

    by_author: dict[str, list[CommitFeatures]] = defaultdict(list)
    for c in commits:
        by_author[c.author].append(c)

    total_commits = len(commits)
    result: dict[str, AuthorBaseline] = {}

    for author, author_commits in by_author.items():
        timestamps = [c.timestamp for c in author_commits]
        first = min(timestamps)
        last = max(timestamps)
        tenure_days = (last - first).days

        messages = [c.message for c in author_commits]
        message_lens = [len(m) for m in messages]
        files_changed_counts = [len(c.files_changed) for c in author_commits]
        hours = [c.hour_of_day for c in author_commits]
        days = [c.day_of_week for c in author_commits]

        result[author] = AuthorBaseline(
            author=author,
            sample_size=len(author_commits),
            tenure_days=tenure_days,
            commit_share=len(author_commits) / total_commits,
            median_message_len=int(median(message_lens)),
            median_files_changed=int(median(files_changed_counts)),
            path_word_ratio=_path_word_ratio(messages),
            typical_hours=_typical_hours(hours),
            typical_days=_typical_days(days),
            regions_touched=_regions_touched(author_commits),
        )

    return result


# Commits touching this many files or more are almost always vendor bumps,
# generated-file refreshes, or whole-repo refactors — they pair every file
# with every other and add O(N²) low-information edges to the co-change
# graph. The cap is the standard MSR-literature mitigation. Tunable per
# call when needed (e.g., a survey that genuinely wants to see refactor
# coupling).
_MEGA_COMMIT_FILE_THRESHOLD = 50


def build_co_changes(
    commits: Sequence[CommitFeatures],
    *,
    max_files_per_commit: int = _MEGA_COMMIT_FILE_THRESHOLD,
) -> list[CoChange]:
    """For every pair of files that co-changed, count and most-recent timestamp.

    Pure function — no I/O. Pairs are returned in canonical order
    (``file_a < file_b`` lexicographically) so each unordered pair has
    exactly one record. Sorted by ``count`` descending, then by pair
    alphabetically for determinism.

    Commits touching more than ``max_files_per_commit`` files are skipped
    — they're typically refactors / vendor bumps that create O(N²)
    low-information edges. Lower the cap for repos where you want stricter
    coupling signal; raise it if you genuinely want to see refactor pairs.
    """
    if not commits:
        return []

    pair_shas: dict[tuple[str, str], list[str]] = defaultdict(list)
    pair_last_seen: dict[tuple[str, str], object] = {}

    for c in commits:
        files = c.files_changed
        if len(files) < 2 or len(files) > max_files_per_commit:
            continue
        # Dedupe within a commit so a file listed twice doesn't pair with itself
        unique_sorted = sorted(set(files))
        sha = c.git_sha or c.id
        for a, b in combinations(unique_sorted, 2):
            key = (a, b)
            pair_shas[key].append(sha)
            existing = pair_last_seen.get(key)
            if existing is None or c.timestamp > existing:
                pair_last_seen[key] = c.timestamp

    result = [
        CoChange(
            file_a=a,
            file_b=b,
            count=len(pair_shas[(a, b)]),
            last_co_changed_at=pair_last_seen[(a, b)],  # type: ignore[arg-type]
            commit_shas=tuple(pair_shas[(a, b)]),
        )
        for (a, b) in pair_shas
    ]
    result.sort(key=lambda c: (-c.count, c.file_a, c.file_b))
    return result


def related_files(
    file_path: str,
    co_changes: Sequence[CoChange],
    *,
    top_n: int = 10,
) -> list[tuple[str, int]]:
    """Top ``top_n`` files most often co-changed with ``file_path``.

    Returns ``[(other_path, count), ...]`` sorted by count descending.
    Looks at both sides of each pair since the canonical-order constraint
    means ``file_path`` may appear as either ``file_a`` or ``file_b``.
    Returns an empty list if ``file_path`` has no co-change edges.
    """
    matches: list[tuple[str, int]] = []
    for cc in co_changes:
        if cc.file_a == file_path:
            matches.append((cc.file_b, cc.count))
        elif cc.file_b == file_path:
            matches.append((cc.file_a, cc.count))
    matches.sort(key=lambda pair: (-pair[1], pair[0]))
    return matches[:top_n]


# --- Act segmentation (#149) ------------------------------------------------
# The project lifespan is diced into proportional windows; structural inflections
# — commit-cadence changepoints, human-contributor-count shifts, and the first
# appearance of a second human contributor — become candidate Act boundaries.
# The count is data-driven, capped to [1, 5]. Boundaries carry a confidence so an
# uncertain one renders dashed (#149 decision 7). All thresholds are named so the
# eyeball-test repos can tune them — the signals were Tom's educated guesses, so
# this is built to be calibrated, not trusted blindly.
_ACT_MAX_COUNT = 5
_ACT_WINDOWS = 24  # proportional windows the lifespan is diced into
_ACT_MIN_COMMITS = 8  # below this the record is too thin to claim a boundary
_ACT_MIN_SPAN_DAYS = 14  # a history shorter than this is a single movement
_ACT_MIN_SPAN_FRAC = (
    0.08  # every Act spans >= this fraction of the timeline (scale-relative)
)
_ACT_CADENCE_RATIO = 2.0  # window-vs-trailing cadence factor that flags a shift
_ACT_CONF_FLOOR = 0.35  # a lone weak signal lands here; agreement/magnitude lifts it

_BOT_MARKERS = ("[bot]", "dependabot", "github-actions", "renovate", "mergify")
_AGENT_MARKERS = ("dispatch-bot", "claude", "copilot", "cursor")


def _is_human_author(author: str, email: str) -> bool:
    """Best-effort "a person, not an AI/bot" test (#149 decision 3).

    Deliberately simple — Tom signed off on "good enough for now". Excludes
    ``[bot]`` suffixes, common CI bots, and known agent identities. The
    contributor-count signal degrades gracefully if one slips through: a stray
    bot shifts a count by one, it does not invent an Act on its own.
    """
    hay = f"{author} {email}".lower()
    return not any(m in hay for m in _BOT_MARKERS + _AGENT_MARKERS)


def _single_act(commits: list[CommitFeatures]) -> list[Act]:
    """One Act spanning the whole record — the honest answer when there is not
    enough signal (or enough commits) to claim a movement boundary."""
    if not commits:
        return []
    return [
        Act(
            id=str(ULID()),
            index=1,
            start=commits[0].timestamp,
            end=commits[-1].timestamp,
            commit_count=len(commits),
            boundary_confidence=1.0,  # the origin is not a guess
            signals=("origin",),
        )
    ]


def build_acts(commits: Sequence[CommitFeatures]) -> list[Act]:
    """Segment the project lifespan into 1-5 structural Acts (#149).

    Pure function — no I/O. Signals (Tom's #149 answers): commit-cadence
    changepoints, human-contributor-count shifts (either direction), and the
    first appearance of a second *human* contributor. The count is data-driven,
    capped to ``[1, 5]``; each Act start carries a confidence in ``[0, 1]`` so an
    uncertain boundary can render dashed. Naming is a later, separate pass — Acts
    come back nameless here.
    """
    ordered = sorted(commits, key=lambda c: c.timestamp)
    if len(ordered) < _ACT_MIN_COMMITS:
        return _single_act(ordered)

    start = ordered[0].timestamp
    end = ordered[-1].timestamp
    span = (end - start).total_seconds()
    if span < _ACT_MIN_SPAN_DAYS * 86400:
        return _single_act(ordered)  # too short a life to hold distinct movements

    def window_of(ts) -> int:
        frac = (ts - start).total_seconds() / span
        return min(_ACT_WINDOWS - 1, max(0, int(frac * _ACT_WINDOWS)))

    counts = [0] * _ACT_WINDOWS
    humans_in: list[set[str]] = [set() for _ in range(_ACT_WINDOWS)]
    seen_humans: set[str] = set()
    second_human_window: int | None = None
    for c in ordered:
        w = window_of(c.timestamp)
        counts[w] += 1
        if _is_human_author(c.author, c.author_email):
            email = c.author_email.lower()
            humans_in[w].add(email)
            if email not in seen_humans:
                seen_humans.add(email)
                if len(seen_humans) == 2 and second_human_window is None:
                    second_human_window = w

    # Candidate boundaries sit *before* a window (between w-1 and w). A window may
    # be lit by more than one signal; agreement raises its confidence later.
    candidates: dict[int, tuple[float, set[str]]] = {}

    def add_candidate(w: int, magnitude: float, signal: str) -> None:
        if w <= 0 or w >= _ACT_WINDOWS:
            return
        score, signals = candidates.get(w, (0.0, set()))
        candidates[w] = (score + magnitude, signals | {signal})

    for w in range(1, _ACT_WINDOWS):  # cadence changepoints
        prior = [counts[i] for i in range(w) if counts[i] > 0]
        if not prior or counts[w] == 0:
            continue
        base = sum(prior) / len(prior)
        ratio = counts[w] / base
        if ratio >= _ACT_CADENCE_RATIO or ratio <= 1 / _ACT_CADENCE_RATIO:
            add_candidate(w, abs(log(ratio)), "cadence-shift")

    # contributor-count shifts (either direction) — compare each active window's
    # roster to the previous *active* one, so a quiet gap isn't read as a
    # departure-and-return.
    prev_roster: set[str] | None = None
    for w in range(_ACT_WINDOWS):
        if not humans_in[w]:
            continue
        if prev_roster is not None:
            delta = len(humans_in[w]) - len(prev_roster)
            if delta != 0:
                add_candidate(w, float(abs(delta)), "contributor-shift")
        prev_roster = humans_in[w]

    if second_human_window and second_human_window > 0:  # discrete strong marker
        add_candidate(second_human_window, 2.0, "second-human")

    if not candidates:
        return _single_act(ordered)

    def first_commit_ts_at(w: int):
        """An Act starts at a real commit, not an interpolated instant."""
        for c in ordered:
            if window_of(c.timestamp) >= w:
                return c.timestamp
        return end

    # Strongest candidates first, but every boundary must sit at least a minimum
    # span from both ends and from each boundary already taken — so no Act is a
    # sliver. The floor is a fraction of the timeline, so it scales with the repo
    # rather than being tuned to any one; the count lands in [1, 5].
    min_gap = _ACT_MIN_SPAN_FRAC * span
    chosen: list[tuple] = []  # (timestamp, score, signals)
    for w in sorted(candidates, key=lambda k: candidates[k][0], reverse=True):
        ts = first_commit_ts_at(w)
        off = (ts - start).total_seconds()
        if off < min_gap or (span - off) < min_gap:
            continue
        if any(abs((ts - c[0]).total_seconds()) < min_gap for c in chosen):
            continue
        score, signals = candidates[w]
        chosen.append((ts, score, signals))
        if len(chosen) >= _ACT_MAX_COUNT - 1:
            break
    if not chosen:
        return _single_act(ordered)
    boundaries = sorted(chosen, key=lambda c: c[0])
    max_score = max((c[1] for c in boundaries), default=1.0) or 1.0
    edges = [start] + [c[0] for c in boundaries] + [end]

    acts: list[Act] = []
    for i in range(len(edges) - 1):
        a_start, a_end = edges[i], edges[i + 1]
        last = i == len(edges) - 2
        n = sum(
            1
            for c in ordered
            if (
                a_start <= c.timestamp <= a_end
                if last
                else a_start <= c.timestamp < a_end
            )
        )
        if i == 0:
            conf, signals = 1.0, ("origin",)
        else:
            _, score, sset = boundaries[i - 1]
            conf = _ACT_CONF_FLOOR + (1 - _ACT_CONF_FLOOR) * min(
                1.0, (score / max_score) * (0.5 + 0.25 * len(sset))
            )
            signals = tuple(sorted(sset))
        acts.append(
            Act(
                id=str(ULID()),
                index=i + 1,
                start=a_start,
                end=a_end,
                commit_count=n,
                boundary_confidence=round(min(1.0, conf), 3),
                signals=signals,
            )
        )
    return acts


def assign_arcs_to_acts(
    acts: Sequence[Act], arc_commit_times: dict[str, list]
) -> dict[str, str]:
    """Assign each arc to the single Act it most correlates with (#149 decision 5).

    ``arc_commit_times`` maps an arc slug to its commits' timestamps. Correlation
    is how many of the arc's commits fall inside an Act's ``[start, end]``.
    Tiebreak: the Act with more commits overall, then the earlier Act. Arcs with
    no datable commits are skipped. Returns ``{arc_slug: act_id}``.
    """
    out: dict[str, str] = {}
    for slug, times in arc_commit_times.items():
        if not times:
            continue
        best_key: tuple[int, int, int] | None = None
        best_id: str | None = None
        for a in acts:
            overlap = sum(1 for t in times if a.start <= t <= a.end)
            if overlap == 0:
                continue
            key = (overlap, a.commit_count, -a.index)
            if best_key is None or key > best_key:
                best_key, best_id = key, a.id
        if best_id is not None:
            out[slug] = best_id
    return out

"""Structural profilers — per-author baselines, region grouping, file co-change."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from itertools import combinations
from math import sqrt
from statistics import median

from antiquarian.models import (
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

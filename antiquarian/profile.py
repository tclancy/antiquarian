"""Person profiler — build per-author baselines from commit features."""

from __future__ import annotations

import re
from collections import defaultdict
from statistics import median

from antiquarian.models import AuthorBaseline, CommitFeatures

_PATH_TOKEN_RE = re.compile(
    r"[/\\]"  # contains a slash
    r"|\.(?:py|js|ts|tsx|jsx|rs|go|rb|java|c|cpp|h|hpp|css|html|md|yml|yaml|toml|json|sql|sh|txt)$"
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
    """IQR of hour_of_day values as (Q1, Q3)."""
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


def build_author_baselines(
    commits: list[CommitFeatures],
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

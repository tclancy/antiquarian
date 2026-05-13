"""Significant Change detectors — score commits by deviation from baselines."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from math import sqrt
from typing import Callable, Protocol, runtime_checkable

from ulid import ULID

from antiquarian.models import AuthorBaseline, CommitFeatures, SignificantChange

_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

_Z_THRESHOLD = 1.5


def _noop(_msg: str) -> None:
    pass


@runtime_checkable
class SignificantChangeDetector(Protocol):
    def detect(
        self,
        commits: Sequence[CommitFeatures],
        baselines: dict[str, AuthorBaseline],
        *,
        top_n: int = 20,
        log: Callable[[str], None] = _noop,
    ) -> list[SignificantChange]: ...


def _stdev(values: list[float], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return sqrt(variance)


def _z_score(value: float, mean: float, sd: float) -> float:
    if sd == 0.0:
        return 0.0
    return (value - mean) / sd


def _hour_distance(hour: int, q1: int, q3: int) -> int:
    """Distance in hours from the typical_hours IQR band. 0 if inside."""
    if q1 <= hour <= q3:
        return 0
    below = (q1 - hour) % 24
    above = (hour - q3) % 24
    return min(below, above)


def _score_message_length(
    commit: CommitFeatures,
    stats: dict[str, tuple[float, float]],
    baseline: AuthorBaseline,
) -> tuple[float, str | None]:
    msg_len = float(len(commit.message))
    msg_mean, msg_sd = stats["message_len"]
    msg_z = abs(_z_score(msg_len, msg_mean, msg_sd))
    if msg_z <= _Z_THRESHOLD:
        return 0.0, None
    ratio = (
        msg_len / baseline.median_message_len
        if baseline.median_message_len > 0
        else msg_len
    )
    return msg_z, f"message {ratio:.1f}x author's median length"


def _score_files_changed(
    commit: CommitFeatures,
    stats: dict[str, tuple[float, float]],
    baseline: AuthorBaseline,
) -> tuple[float, str | None]:
    files_count = float(len(commit.files_changed))
    files_mean, files_sd = stats["files_changed"]
    files_z = abs(_z_score(files_count, files_mean, files_sd))
    if files_z <= _Z_THRESHOLD:
        return 0.0, None
    return files_z, (
        f"touched {int(files_count)} files; "
        f"author's median is {baseline.median_files_changed}"
    )


def _score_diff_size(
    commit: CommitFeatures,
    stats: dict[str, tuple[float, float]],
) -> tuple[float, str | None]:
    diff_size = float(commit.additions + commit.deletions)
    diff_mean, diff_sd = stats["diff_size"]
    diff_z = abs(_z_score(diff_size, diff_mean, diff_sd))
    if diff_z <= _Z_THRESHOLD:
        return 0.0, None
    return diff_z, f"diff size {int(diff_size)} lines (z={diff_z:.1f})"


def _score_hour_of_day(
    commit: CommitFeatures,
    baseline: AuthorBaseline,
) -> tuple[float, str | None]:
    hour_dist = _hour_distance(
        commit.hour_of_day, baseline.typical_hours[0], baseline.typical_hours[1]
    )
    if hour_dist <= 3:
        return 0.0, None
    return hour_dist / 3.0, (
        f"committed at hour {commit.hour_of_day}; "
        f"typical window is {baseline.typical_hours[0]}–{baseline.typical_hours[1]}"
    )


def _score_day_of_week(
    commit: CommitFeatures,
    baseline: AuthorBaseline,
) -> tuple[float, str | None]:
    if not baseline.typical_days or commit.day_of_week in baseline.typical_days:
        return 0.0, None
    return 1.0, (
        f"committed on {_DAY_NAMES[commit.day_of_week]}; "
        f"typical days: {', '.join(_DAY_NAMES[d] for d in baseline.typical_days)}"
    )


class StatisticalBaselineDetector:
    """Score each commit by how unusual it is relative to its author's baseline.

    Z-scores are computed from the raw commit data (mean + stdev) rather than
    the AuthorBaseline medians, so we get proper statistical deviation.
    AuthorBaseline medians are still used for human-readable reason strings.
    """

    def detect(
        self,
        commits: Sequence[CommitFeatures],
        baselines: dict[str, AuthorBaseline],
        *,
        top_n: int = 20,
        log: Callable[[str], None] = _noop,
    ) -> list[SignificantChange]:
        if not commits:
            return []

        by_author: dict[str, list[CommitFeatures]] = defaultdict(list)
        for c in commits:
            by_author[c.author].append(c)

        author_stats = self._compute_author_stats(by_author)
        log(f"[sc] {len(commits)} commits, {len(by_author)} authors")

        scored: list[tuple[float, CommitFeatures, list[str]]] = []
        for author, author_commits in by_author.items():
            stats = author_stats.get(author)
            baseline = baselines.get(author)
            if stats is None or baseline is None:
                continue
            for commit in author_commits:
                score, reasons = self._score_commit(commit, stats, baseline)
                if score > 0:
                    scored.append((score, commit, reasons))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_n]

        log(f"[sc] top {len(top)} significant changes (of {len(scored)} scored > 0)")

        return [
            SignificantChange(
                id=str(ULID()),
                commits=[c.git_sha] if c.git_sha else [c.id],
                score=score,
                reasons=reasons,
                region=self._primary_region(c),
                detector_name="statistical",
            )
            for score, c, reasons in top
        ]

    def _compute_author_stats(
        self, by_author: dict[str, list[CommitFeatures]]
    ) -> dict[str, dict[str, tuple[float, float]]]:
        """Compute mean + stdev per author for each numeric signal."""
        result: dict[str, dict[str, tuple[float, float]]] = {}
        for author, commits in by_author.items():
            msg_lens = [float(len(c.message)) for c in commits]
            files_counts = [float(len(c.files_changed)) for c in commits]
            diff_sizes = [float(c.additions + c.deletions) for c in commits]

            msg_mean = sum(msg_lens) / len(msg_lens)
            files_mean = sum(files_counts) / len(files_counts)
            diff_mean = sum(diff_sizes) / len(diff_sizes)

            result[author] = {
                "message_len": (msg_mean, _stdev(msg_lens, msg_mean)),
                "files_changed": (files_mean, _stdev(files_counts, files_mean)),
                "diff_size": (diff_mean, _stdev(diff_sizes, diff_mean)),
            }
        return result

    def _score_commit(
        self,
        commit: CommitFeatures,
        stats: dict[str, tuple[float, float]],
        baseline: AuthorBaseline,
    ) -> tuple[float, list[str]]:
        """Return (composite_score, [reason_strings])."""
        signals = [
            _score_message_length(commit, stats, baseline),
            _score_files_changed(commit, stats, baseline),
            _score_diff_size(commit, stats),
            _score_hour_of_day(commit, baseline),
            _score_day_of_week(commit, baseline),
        ]
        reasons = [reason for _, reason in signals if reason is not None]
        total = sum(score for score, _ in signals)
        return total, reasons

    def _primary_region(self, commit: CommitFeatures) -> str | None:
        if not commit.files_changed:
            return None
        parts = commit.files_changed[0].split("/")
        return parts[0] if len(parts) > 1 else None

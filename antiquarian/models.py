"""Data shapes shared across Antiquarian. See GitHub issue #2 for design rationale."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class CommitFeatures:
    id: str
    git_sha: str | None
    jj_change_id: str | None
    jj_commit_id: str | None
    author: str
    author_email: str
    timestamp: datetime
    hour_of_day: int
    day_of_week: int
    message: str
    files_changed: list[str]
    additions: int
    deletions: int
    pr_number: int | None
    pr_body: str | None
    is_revert: bool = False
    commit_binge_window_minutes: int | None = None


@dataclass(frozen=True)
class AuthorBaseline:
    author: str
    sample_size: int
    tenure_days: int
    commit_share: float
    median_message_len: int
    median_files_changed: int
    path_word_ratio: float
    typical_hours: tuple[int, int]
    typical_days: tuple[int, ...]
    regions_touched: dict[str, int]


@dataclass(frozen=True)
class RegionDefinition:
    name: str
    path_prefix: str
    introduced_in: str | None
    notable_evolutions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RepoProfile:
    stage_marker: Literal["commit", "squash", "pr"]
    median_message_len: int
    path_word_ratio: float
    pr_signal_strength: float
    regions: list[RegionDefinition]
    per_author: dict[str, AuthorBaseline]
    per_region: dict[str, AuthorBaseline]
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SignificantChange:
    id: str
    commits: list[str]
    score: float
    reasons: list[str]
    region: str | None
    detector_name: str


@dataclass(frozen=True)
class TodoAnnotation:
    kind: Literal["TODO", "FIXME", "XXX", "HACK"]
    line_number: int
    text: str
    introduced_commit: str
    introduced_at: datetime
    introduced_by: str
    age_days: int

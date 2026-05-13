"""Tests for narrative prompt construction."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from antiquarian.models import CommitFeatures, TodoAnnotation
from antiquarian.narrative import (
    THRESHOLD_BYTES,
    _compress_message,
    _is_low_info_commit,
    _run_claude_p,
    _sanitize_for_claude,
    build_survey_prompt,
    build_user_prompt,
)


class TestCompressMessage:
    """Issue #36 MVP — truncate verbose commit messages."""

    def test_short_message_unchanged(self):
        msg = "Fix a typo"
        assert _compress_message(msg) == msg

    def test_message_exactly_at_cap_unchanged(self):
        msg = "x" * 500
        assert _compress_message(msg) == msg

    def test_truncates_at_paragraph_when_first_para_fits(self):
        first_para = "Initial release of BetterBlue v1.0"
        body = "x" * 700
        msg = f"{first_para}\n\n{body}"
        out = _compress_message(msg)
        assert out.startswith(first_para)
        assert "truncated" in out
        assert len(out) < len(msg)
        # Truncated-byte count is accurate
        truncated = len(msg) - 500
        assert f"[…{truncated} more chars truncated]" in out

    def test_hard_truncates_when_first_para_too_long(self):
        msg = "x" * 1000  # no paragraph break
        out = _compress_message(msg)
        assert out.startswith("x" * 500)
        assert "truncated" in out
        # 500 chars + truncation tail
        truncated = 500
        assert f"[…{truncated} more chars truncated]" in out

    def test_custom_cap(self):
        msg = "abcdefghij" * 20  # 200 chars
        out = _compress_message(msg, max_chars=50)
        assert len(out) < len(msg)
        assert "truncated" in out

    def test_preserves_betterblue_v1_release_notes_first_line(self):
        """The canonical motivating case: BetterBlue's v1.0 release notes."""
        msg = (
            "Initial release of BetterBlue v1.0\n\n"
            "BetterBlue is a modern iOS app for controlling Hyundai and Kia "
            "vehicles using BlueLink and Kia Connect services. This release "
            "includes:\n\n"
            "Features:\n"
            "- Remote vehicle control (lock/unlock, climate, charging)\n"
            "- Multi-powertrain support (BEV, gas, PHEV)\n"
            "- Apple Watch app with full vehicle control\n"
            "- iOS widgets for quick status monitoring\n"
            "- HTTP request/response logging for debugging\n"
            "- Dark mode and modern SwiftUI interface\n"
            "- Multiple account management\n"
            "- Fake vehicle mode for testing\n\n"
            "Technical:\n"
            "- Built with SwiftUI and SwiftData\n"
            "- Uses async/await for modern Swift concurrency\n"
            "- Comprehensive test coverage with fake API\n"
            "- Clean architecture with separate BetterBlueKit package"
        )
        out = _compress_message(msg)
        assert out.startswith("Initial release of BetterBlue v1.0")
        assert len(out) < len(msg)


class TestSanitizeForClaude:
    """Coverage for the issue #16 fix — strip the patterns that hang `claude -p`."""

    def test_strips_robot_attribution_line(self) -> None:
        msg = (
            "Initial release\n\n"
            "Some description.\n\n"
            "🤖 Generated with [Claude Code](https://claude.ai/code)\n\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>"
        )
        out = _sanitize_for_claude(msg)
        assert "🤖" not in out
        assert "claude.ai/code" not in out
        assert "Co-Authored-By: Claude <" not in out
        assert "Initial release" in out
        assert "Some description." in out

    def test_keeps_parameterized_coauthor(self) -> None:
        """The form with model parameters (used by dispatch-bot[bot]) does not
        trigger the hang and should be preserved."""
        msg = (
            "Some commit\n\n"
            "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
        )
        out = _sanitize_for_claude(msg)
        assert "Claude Opus 4.7 (1M context)" in out

    def test_idempotent(self) -> None:
        msg = (
            "test\n\n🤖 Generated with [Claude Code](https://claude.ai/code)\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>"
        )
        once = _sanitize_for_claude(msg)
        twice = _sanitize_for_claude(once)
        assert once == twice

    def test_no_attribution_unchanged(self) -> None:
        msg = "Regular commit\n\nNo attribution here"
        assert _sanitize_for_claude(msg) == msg

    def test_empty_string(self) -> None:
        assert _sanitize_for_claude("") == ""


def _commit(
    *,
    sha: str = "abc12345",
    author: str = "dev",
    message: str = "fix stuff",
    additions: int = 5,
    deletions: int = 2,
) -> CommitFeatures:
    return CommitFeatures(
        id="01ABCDEF",
        git_sha=sha,
        jj_change_id=None,
        jj_commit_id=None,
        author=author,
        author_email=f"{author}@example.com",
        timestamp=datetime(2026, 1, 15, 10, 30, tzinfo=timezone.utc),
        hour_of_day=10,
        day_of_week=3,
        message=message,
        files_changed=["src/main.py"],
        additions=additions,
        deletions=deletions,
        pr_number=None,
        pr_body=None,
    )


def _todo(
    *, kind: str = "TODO", line: int = 42, text: str = "clean this up"
) -> TodoAnnotation:
    return TodoAnnotation(
        kind=kind,
        line_number=line,
        text=text,
        introduced_commit="deadbeef",
        introduced_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
        introduced_by="dev",
        age_days=5,
    )


class TestBuildUserPrompt:
    def test_contains_file_and_repo(self):
        prompt = build_user_prompt("src/main.py", "acme/repo", [_commit()], [])
        assert "**File:** `src/main.py`" in prompt
        assert "**Repository:** acme/repo" in prompt

    def test_commit_count(self):
        commits = [_commit(sha="aaa"), _commit(sha="bbb")]
        prompt = build_user_prompt("f.py", "r", commits, [])
        assert "**Commit count:** 2" in prompt

    def test_todo_rendered(self):
        prompt = build_user_prompt("f.py", "r", [_commit()], [_todo()])
        assert "**TODO** at line 42" in prompt
        assert "clean this up" in prompt

    def test_no_todos_shows_none(self):
        prompt = build_user_prompt("f.py", "r", [_commit()], [])
        assert "(none)" in prompt

    def test_pr_body_included(self):
        c = CommitFeatures(
            id="01X",
            git_sha="pr12345",
            jj_change_id=None,
            jj_commit_id=None,
            author="dev",
            author_email="dev@e.com",
            timestamp=datetime(2026, 1, 15, tzinfo=timezone.utc),
            hour_of_day=10,
            day_of_week=3,
            message="feat: add widget",
            files_changed=["widget.py"],
            additions=50,
            deletions=0,
            pr_number=99,
            pr_body="Added the widget component for dashboard.",
        )
        prompt = build_user_prompt("widget.py", "r", [c], [])
        assert "**PR #99**" in prompt
        assert "Added the widget component" in prompt


class TestSizeAwareCompressor:
    """Issue #36 — prompt compression when build_user_prompt exceeds THRESHOLD_BYTES."""

    def test_small_prompt_uncompressed(self):
        """A prompt that already fits passes through unchanged."""
        commits = [_commit(sha="aaaaaaaa", message="initial commit")]
        prompt = build_user_prompt("f.py", "r", commits, [])
        assert len(prompt) <= THRESHOLD_BYTES
        # No "Also touched" trail appears when nothing was dropped
        assert "Also touched in" not in prompt
        # Original commit count line reflects all commits
        assert "**Commit count:** 1" in prompt

    def test_oversize_drops_low_info_commits(self):
        """A low-info commit (short msg, tiny diff) drops into the trail when needed."""
        commits = [
            _commit(
                sha="11111111",
                message="A real substantive change with meaningful description",
                additions=200,
                deletions=10,
            ),
            _commit(sha="22222222", message="typo", additions=1, deletions=1),
        ]
        # Threshold sized to fit "substantive + trail" (~593 B) but not
        # "both commits in default render" (~610 B) — forces phase 2 only.
        prompt = build_user_prompt("f.py", "r", commits, [], threshold_bytes=600)
        assert "Also touched in" in prompt
        assert "22222222" in prompt
        # The substantive commit survives as a real block
        assert "### [1] 11111111" in prompt

    def test_oversize_preserves_all_shas_somewhere(self):
        """No commit is silently dropped — every SHA appears either as a header or trail."""
        commits = [
            _commit(
                sha=f"sha{i:05d}",
                message="real change " * 30,
                additions=50,
                deletions=20,
            )
            for i in range(8)
        ]
        prompt = build_user_prompt("f.py", "r", commits, [], threshold_bytes=2500)
        for c in commits:
            assert c.git_sha[:8] in prompt

    def test_threshold_respected_for_typical_inputs(self):
        """A realistic-sized commit history compresses under the threshold."""
        # 10 commits, each with ~1 KB of message — uncompressed prompt ~10 KB+.
        commits = [
            _commit(
                sha=f"abcd{i:04d}",
                message=(f"Commit {i}: " + "blah " * 200),
                additions=50,
                deletions=20,
            )
            for i in range(10)
        ]
        prompt = build_user_prompt("f.py", "r", commits, [])
        assert len(prompt) <= THRESHOLD_BYTES, (
            f"prompt was {len(prompt)} bytes, threshold {THRESHOLD_BYTES}"
        )

    def test_custom_threshold_honored(self):
        commits = [
            _commit(
                sha=f"abcd{i:04d}",
                message=(f"Commit {i}: " + "blah " * 100),
                additions=50,
                deletions=20,
            )
            for i in range(5)
        ]
        prompt_strict = build_user_prompt(
            "f.py", "r", commits, [], threshold_bytes=2000
        )
        prompt_loose = build_user_prompt(
            "f.py", "r", commits, [], threshold_bytes=100_000
        )
        assert len(prompt_strict) <= 2000
        # Loose threshold preserves more — at minimum, less compression happened
        assert "Also touched in" not in prompt_loose

    def test_idempotent_inputs_give_identical_prompts(self):
        """Running with the same inputs twice yields byte-identical output."""
        commits = [
            _commit(sha="aaaaaaaa", message="first", additions=10, deletions=2),
            _commit(
                sha="bbbbbbbb", message="second " * 200, additions=100, deletions=20
            ),
        ]
        # Pin the date so the prompt is deterministic across the two calls
        first = build_user_prompt("f.py", "r", commits, [])
        second = build_user_prompt("f.py", "r", commits, [])
        assert first == second

    def test_dropped_count_reflected_in_trail(self):
        commits = [
            _commit(
                sha="big00001",
                message="A real substantive change",
                additions=200,
                deletions=10,
            ),
            _commit(sha="lo000001", message="x", additions=1, deletions=0),
            _commit(sha="lo000002", message="y", additions=1, deletions=0),
        ]
        # Phase 2 yields ~575 B (substantive + 2-SHA trail); phase 1 is 666 B
        prompt = build_user_prompt("f.py", "r", commits, [], threshold_bytes=600)
        assert "Also touched in" in prompt
        assert "2 commit(s) elided" in prompt
        assert "lo000001" in prompt
        assert "lo000002" in prompt


class TestIsLowInfoCommit:
    """The cheap heuristic that picks compression candidates."""

    def test_short_msg_tiny_diff_is_low_info(self):
        c = _commit(message="fix typo", additions=1, deletions=1)
        assert _is_low_info_commit(c) is True

    def test_long_msg_not_low_info(self):
        c = _commit(
            message="This commit explains a real architectural change in detail",
            additions=1,
            deletions=1,
        )
        assert _is_low_info_commit(c) is False

    def test_big_diff_not_low_info_even_with_short_msg(self):
        c = _commit(message="wip", additions=300, deletions=100)
        assert _is_low_info_commit(c) is False

    def test_whitespace_only_msg_is_low_info(self):
        c = _commit(message="   \n  ", additions=1, deletions=0)
        assert _is_low_info_commit(c) is True


class TestBuildSurveyPrompt:
    def test_contains_repo_and_file_count(self):
        stories = [("src/a.py", "Story A"), ("src/b.py", "Story B")]
        prompt = build_survey_prompt("acme/repo", stories)
        assert "**Repository:** acme/repo" in prompt
        assert "**Files surveyed:** 2" in prompt

    def test_each_story_appears(self):
        stories = [
            ("deploy.py", "The deploy story narrative."),
            ("config.py", "The config story narrative."),
        ]
        prompt = build_survey_prompt("r", stories)
        assert "Per-file story: `deploy.py`" in prompt
        assert "The deploy story narrative." in prompt
        assert "Per-file story: `config.py`" in prompt
        assert "The config story narrative." in prompt

    def test_stories_numbered_sequentially(self):
        stories = [("a.py", "A"), ("b.py", "B"), ("c.py", "C")]
        prompt = build_survey_prompt("r", stories)
        assert "[1] Per-file story: `a.py`" in prompt
        assert "[2] Per-file story: `b.py`" in prompt
        assert "[3] Per-file story: `c.py`" in prompt

    def test_ends_with_synthesis_instruction(self):
        prompt = build_survey_prompt("r", [("x.py", "story")])
        assert "## Files surveyed" in prompt
        assert "no preamble" in prompt

    def test_single_file_survey(self):
        prompt = build_survey_prompt("r", [("only.py", "The only file.")])
        assert "**Files surveyed:** 1" in prompt
        assert "Per-file story: `only.py`" in prompt

    def test_baselines_included_when_provided(self):
        from antiquarian.models import AuthorBaseline

        baselines = {
            "Alice": AuthorBaseline(
                author="Alice",
                sample_size=10,
                tenure_days=180,
                commit_share=0.7,
                median_message_len=50,
                median_files_changed=3,
                path_word_ratio=0.2,
                typical_hours=(9, 17),
                typical_days=(0, 1, 2, 3, 4),
                regions_touched={"src": 8, "tests": 5},
            ),
            "Bob": AuthorBaseline(
                author="Bob",
                sample_size=4,
                tenure_days=30,
                commit_share=0.3,
                median_message_len=20,
                median_files_changed=1,
                path_word_ratio=0.1,
                typical_hours=(14, 20),
                typical_days=(3, 4),
                regions_touched={"src": 3},
            ),
        }
        prompt = build_survey_prompt("r", [("x.py", "story")], baselines)
        assert "Per-author baselines" in prompt
        assert "**Alice**" in prompt
        assert "**Bob**" in prompt
        assert "10 commits over 180d" in prompt
        assert "70% share" in prompt

    def test_baselines_sorted_by_commit_count(self):
        from antiquarian.models import AuthorBaseline

        baselines = {
            "Minor": AuthorBaseline(
                author="Minor",
                sample_size=1,
                tenure_days=0,
                commit_share=0.1,
                median_message_len=10,
                median_files_changed=1,
                path_word_ratio=0.0,
                typical_hours=(10, 10),
                typical_days=(0,),
                regions_touched={"src": 1},
            ),
            "Major": AuthorBaseline(
                author="Major",
                sample_size=9,
                tenure_days=100,
                commit_share=0.9,
                median_message_len=40,
                median_files_changed=2,
                path_word_ratio=0.1,
                typical_hours=(8, 18),
                typical_days=(0, 1, 2, 3, 4),
                regions_touched={"src": 7},
            ),
        }
        prompt = build_survey_prompt("r", [("x.py", "s")], baselines)
        major_pos = prompt.index("**Major**")
        minor_pos = prompt.index("**Minor**")
        assert major_pos < minor_pos

    def test_no_baselines_omits_section(self):
        prompt = build_survey_prompt("r", [("x.py", "story")])
        assert "Per-author baselines" not in prompt

    def test_empty_baselines_omits_section(self):
        prompt = build_survey_prompt("r", [("x.py", "story")], {})
        assert "Per-author baselines" not in prompt


class TestSurveySystemPrompt:
    def test_dramatis_personae_section_required(self):
        from antiquarian.narrative import SURVEY_SYSTEM_PROMPT

        assert "## Dramatis Personae" in SURVEY_SYSTEM_PROMPT

    def test_tone_rules_present(self):
        from antiquarian.narrative import SURVEY_SYSTEM_PROMPT

        assert "Hemingway" in SURVEY_SYSTEM_PROMPT
        assert "Default to kind" in SURVEY_SYSTEM_PROMPT


def _completed(stdout: str = "ok") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["claude"], returncode=0, stdout=stdout, stderr=""
    )


def _timeout() -> subprocess.TimeoutExpired:
    return subprocess.TimeoutExpired(cmd=["claude"], timeout=300)


class TestRunClaudeP:
    """Retry behavior for ``_run_claude_p`` (issue #31)."""

    def test_success_on_first_attempt_does_not_log_retry(self) -> None:
        logs: list[str] = []
        sleeps: list[float] = []
        with patch(
            "antiquarian.narrative.subprocess.run", return_value=_completed("yes")
        ):
            result = _run_claude_p(
                ["claude", "-p"], "hi", 300, log=logs.append, sleep=sleeps.append
            )
        assert result.stdout == "yes"
        assert logs == []
        assert sleeps == []

    def test_retries_on_timeout_then_succeeds(self) -> None:
        logs: list[str] = []
        sleeps: list[float] = []
        side_effects = [_timeout(), _timeout(), _completed("eventually")]
        with patch(
            "antiquarian.narrative.subprocess.run", side_effect=side_effects
        ) as mock_run:
            result = _run_claude_p(
                ["claude", "-p"],
                "hi",
                300,
                base_backoff_seconds=1.0,
                log=logs.append,
                sleep=sleeps.append,
            )
        assert result.stdout == "eventually"
        assert mock_run.call_count == 3
        assert len(logs) == 2
        assert all("retrying" in m for m in logs)
        assert len(sleeps) == 2
        # Exponential: ~1.0, ~3.0 (with up to 20% jitter on top)
        assert 1.0 <= sleeps[0] < 1.21
        assert 3.0 <= sleeps[1] < 3.61

    def test_raises_after_max_attempts(self) -> None:
        logs: list[str] = []
        with patch(
            "antiquarian.narrative.subprocess.run",
            side_effect=[_timeout(), _timeout(), _timeout()],
        ):
            with pytest.raises(subprocess.TimeoutExpired):
                _run_claude_p(
                    ["claude", "-p"],
                    "hi",
                    300,
                    base_backoff_seconds=0.01,
                    log=logs.append,
                    sleep=lambda _s: None,
                )
        # Two "retrying" logs (attempts 1 and 2) + one "giving up" log (attempt 3)
        assert len(logs) == 3
        assert "giving up" in logs[-1]

    def test_retries_called_process_error_then_succeeds(self) -> None:
        """Issue #39 — non-zero exits can be transient too."""
        logs: list[str] = []
        sleeps: list[float] = []
        err = subprocess.CalledProcessError(returncode=1, cmd=["claude"], stderr="")
        with patch(
            "antiquarian.narrative.subprocess.run",
            side_effect=[err, _completed("recovered")],
        ) as mock_run:
            result = _run_claude_p(
                ["claude", "-p"],
                "hi",
                300,
                base_backoff_seconds=0.01,
                log=logs.append,
                sleep=sleeps.append,
            )
        assert result.stdout == "recovered"
        assert mock_run.call_count == 2
        assert len(logs) == 1
        assert "exited 1" in logs[0]
        assert "retrying" in logs[0]

    def test_raises_called_process_error_after_max_attempts(self) -> None:
        logs: list[str] = []
        err = subprocess.CalledProcessError(returncode=2, cmd=["claude"], stderr="bad")
        with patch(
            "antiquarian.narrative.subprocess.run", side_effect=[err, err]
        ) as mock_run:
            with pytest.raises(subprocess.CalledProcessError) as info:
                _run_claude_p(
                    ["claude", "-p"],
                    "hi",
                    300,
                    base_backoff_seconds=0.01,
                    log=logs.append,
                    sleep=lambda _s: None,
                )
        assert info.value.returncode == 2
        assert mock_run.call_count == 2
        # 1 "retrying" log + 1 "giving up" log
        assert len(logs) == 2
        assert "giving up" in logs[-1]

    def test_separate_caps_for_timeout_and_called_process_error(self) -> None:
        """Timeout cap is 3 by default; CPE cap is 2. Different counters."""
        logs: list[str] = []
        side_effects = [
            _timeout(),
            subprocess.CalledProcessError(returncode=1, cmd=["claude"]),
            _completed("ok"),
        ]
        with patch(
            "antiquarian.narrative.subprocess.run", side_effect=side_effects
        ) as mock_run:
            result = _run_claude_p(
                ["claude", "-p"],
                "hi",
                300,
                base_backoff_seconds=0.01,
                log=logs.append,
                sleep=lambda _s: None,
            )
        assert result.stdout == "ok"
        assert mock_run.call_count == 3
        assert any("timed out" in m for m in logs)
        assert any("exited 1" in m for m in logs)

    def test_custom_max_attempts_honored(self) -> None:
        with patch(
            "antiquarian.narrative.subprocess.run",
            side_effect=[_timeout(), _completed("ok")],
        ) as mock_run:
            result = _run_claude_p(
                ["claude", "-p"],
                "hi",
                300,
                max_attempts=2,
                base_backoff_seconds=0.01,
                sleep=lambda _s: None,
            )
        assert result.stdout == "ok"
        assert mock_run.call_count == 2

"""Tests for narrative prompt construction."""

from __future__ import annotations

from datetime import datetime, timezone

from antiquarian.models import CommitFeatures, TodoAnnotation
from antiquarian.narrative import (
    _sanitize_for_claude,
    build_survey_prompt,
    build_user_prompt,
)


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

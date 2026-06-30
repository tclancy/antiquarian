"""Fetch PR descriptions for commits via the gh CLI."""

from __future__ import annotations

import dataclasses
import json
import re
import subprocess
from pathlib import Path

from antiquarian.models import CommitFeatures


def parse_github_repo_url(url: str) -> tuple[str, str] | None:
    """Return ``(owner, name)`` parsed from a GitHub remote URL, or ``None``."""
    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?/?$", url)
    if not m:
        return None
    return m.group(1), m.group(2)


def detect_github_repo(repo_path: str | Path) -> tuple[str, str] | None:
    """Return ``(owner, name)`` of the GitHub repo at ``repo_path``'s origin remote, or ``None``."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return None
    return parse_github_repo_url(result.stdout.strip())


def pr_for_commit(owner: str, repo: str, commit_sha: str) -> tuple[int, str] | None:
    """Return ``(pr_number, pr_body)`` for the PR that merged ``commit_sha``, or ``None``."""
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{owner}/{repo}/commits/{commit_sha}/pulls",
                "--jq",
                ".[0]",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None

    output = result.stdout.strip()
    if not output or output == "null":
        return None
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    number = data.get("number")
    body = data.get("body") or ""
    if number is None:
        return None
    return int(number), body


def enrich_with_pr(features: CommitFeatures, owner: str, repo: str) -> CommitFeatures:
    """Return a copy of ``features`` with PR fields populated if a PR is found."""
    if features.git_sha is None:
        return features
    pr = pr_for_commit(owner, repo, features.git_sha)
    if pr is None:
        return features
    pr_number, pr_body = pr
    return dataclasses.replace(features, pr_number=pr_number, pr_body=pr_body)

"""Guards for the Marketplace-packaged composite Action (#89).

`action.yml` at the repo root is what makes Antiquarian installable as
`uses: tclancy/antiquarian@v1`. GitHub silently refuses to publish — or
list — an action whose metadata is malformed, so these tests encode the
Marketplace requirements as a stricture rather than trusting a one-time
eyeball pass.

Requirements covered:
- file exists at the repo root (Marketplace looks there, not in .github/)
- required top-level keys: name, description, runs
- runs.using == 'composite'
- branding present with a valid color and a non-empty icon
- every input referenced via inputs.<x> in the step bodies is declared
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

# GitHub's allowed branding colors for Marketplace listings.
# https://docs.github.com/actions/sharing-automations/creating-actions/metadata-syntax-for-github-actions#brandingcolor
VALID_BRANDING_COLORS = {
    "white",
    "yellow",
    "blue",
    "green",
    "orange",
    "red",
    "purple",
    "gray-dark",
}

ACTION_YML = Path(__file__).resolve().parent.parent / "action.yml"


def _load_action() -> dict:
    assert ACTION_YML.exists(), (
        "action.yml must live at the repo root for GitHub Marketplace to find it"
    )
    with ACTION_YML.open() as fh:
        return yaml.safe_load(fh)


def test_required_top_level_keys():
    action = _load_action()
    for key in ("name", "description", "runs"):
        assert key in action, f"action.yml is missing required key '{key}'"
    assert action["name"].strip(), "action name must be non-empty"
    assert action["description"].strip(), "action description must be non-empty"


def test_runs_is_composite():
    action = _load_action()
    assert action["runs"].get("using") == "composite"
    assert action["runs"].get("steps"), "composite action must declare steps"


def test_branding_is_valid_for_marketplace():
    action = _load_action()
    branding = action.get("branding")
    assert branding, "Marketplace listing requires a 'branding' block"
    assert branding.get("color") in VALID_BRANDING_COLORS, (
        f"branding.color must be one of {sorted(VALID_BRANDING_COLORS)}"
    )
    assert branding.get("icon", "").strip(), "branding.icon must be a non-empty string"


def test_every_referenced_input_is_declared():
    """Catch typos like inputs.github_token vs the declared github-token."""
    declared = set(_load_action().get("inputs", {}))
    referenced = set(re.findall(r"inputs\.([a-zA-Z0-9_-]+)", ACTION_YML.read_text()))
    undeclared = referenced - declared
    assert not undeclared, (
        f"action.yml references undeclared inputs: {sorted(undeclared)}"
    )


def test_outputs_reference_real_steps():
    """Outputs wired to steps.<id>.outputs must point at a declared step id."""
    action = _load_action()
    step_ids = {s.get("id") for s in action["runs"]["steps"] if s.get("id")}
    output_block = yaml.safe_dump(action.get("outputs", {}))
    referenced = set(re.findall(r"steps\.([a-zA-Z0-9_-]+)\.outputs", output_block))
    missing = referenced - step_ids
    assert not missing, (
        f"outputs reference steps with no matching id: {sorted(missing)}"
    )

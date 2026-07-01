"""Tests for the emergent Act-naming pass (#149 phase 2).

The LLM call itself is mocked with a fake backend — these pin the prompt
assembly, the tolerant parse, the signature keying, persistence, and that the
renderer reads a persisted name onto the Act band.
"""

from __future__ import annotations

import json
from pathlib import Path

from antiquarian.narrative import build_act_naming_prompt, synthesize_act_names
from antiquarian.pipeline import generate_act_names
from antiquarian.profile import act_signature
from antiquarian.render import render_acts_atom
from antiquarian.render_data import extract_render_data


class FakeBackend:
    """A NarrativeBackend stand-in that returns canned text and records the prompt."""

    name = "fake"

    def __init__(self, output: str):
        self.output = output
        self.seen: tuple[str, str] | None = None

    def synthesize(self, system_prompt, user_prompt, *, timeout_seconds=300, log=None):
        self.seen = (system_prompt, user_prompt)
        return self.output


def _acts():
    return [
        {
            "index": 1,
            "start": "2020-01-01T00:00:00+00:00",
            "end": "2020-09-01T00:00:00+00:00",
            "commit_count": 50,
            "signals": ["origin"],
            "arc_slugs": ["initial-sketch"],
        },
        {
            "index": 2,
            "start": "2020-09-01T00:00:00+00:00",
            "end": "2022-01-01T00:00:00+00:00",
            "commit_count": 80,
            "signals": ["cadence-shift", "second-human"],
            "arc_slugs": [],
        },
    ]


class TestSynthesizeActNames:
    def test_keys_are_boundary_signatures(self):
        fb = FakeBackend("1: The First Cut\n2: The Long Climb")
        names = synthesize_act_names(_acts(), backend=fb)
        assert (
            names[
                act_signature("2020-01-01T00:00:00+00:00", "2020-09-01T00:00:00+00:00")
            ]
            == "The First Cut"
        )
        assert (
            names[
                act_signature("2020-09-01T00:00:00+00:00", "2022-01-01T00:00:00+00:00")
            ]
            == "The Long Climb"
        )

    def test_parse_tolerates_prose_and_separators(self):
        fb = FakeBackend("Sure!\n1 — The First Cut\n2. The Long Climb\nhope that helps")
        names = synthesize_act_names(_acts(), backend=fb)
        assert set(names.values()) == {"The First Cut", "The Long Climb"}

    def test_parse_tolerates_act_prefix_and_markdown(self):
        # The model tends to echo the "Act N" phrasing it was fed, and may bold
        # names — both must still parse.
        fb = FakeBackend("Act 1: **The First Cut**\n2) The Long Climb")
        names = synthesize_act_names(_acts(), backend=fb)
        assert set(names.values()) == {"The First Cut", "The Long Climb"}

    def test_unnamed_act_is_left_out(self):
        fb = FakeBackend("1: Only This One")  # model skipped act 2
        names = synthesize_act_names(_acts(), backend=fb)
        assert list(names.values()) == ["Only This One"]  # act 2 simply unnamed

    def test_empty_acts_makes_no_call(self):
        fb = FakeBackend("should not be used")
        assert synthesize_act_names([], backend=fb) == {}
        assert fb.seen is None

    def test_prompt_carries_member_arcs_and_survey(self):
        fb = FakeBackend("1: X\n2: Y")
        synthesize_act_names(
            _acts(), {"initial-sketch": "Initial sketch"}, "the survey text", backend=fb
        )
        _, user = fb.seen
        assert "Initial sketch" in user  # member arc name, not the raw slug
        assert "the survey text" in user

    def test_prompt_uses_arc_name_over_slug(self):
        prompt = build_act_naming_prompt(_acts(), {"initial-sketch": "Initial sketch"})
        assert "Initial sketch" in prompt
        assert "no named arcs" in prompt  # act 2 has none


class TestPersistenceAndRender:
    def test_generate_act_names_writes_signature_keyed_file(self, seeded_repo: Path):
        fb = FakeBackend("1: The Beginning")  # seeded repo → a single act
        names, path = generate_act_names(seeded_repo, backend=fb)
        assert path == seeded_repo / ".antiquarian" / "act_names.json"
        assert path.exists()
        assert list(names.values()) == ["The Beginning"]
        on_disk = json.loads(path.read_text())
        assert on_disk == names  # persisted exactly what was returned

    def test_parse_failure_does_not_clobber_existing_names(self, seeded_repo: Path):
        # A good run writes names; a later run whose output doesn't parse must
        # NOT overwrite them with {} (silent-truncation guard).
        good, path = generate_act_names(
            seeded_repo, backend=FakeBackend("1: The Beginning")
        )
        assert good
        names, _ = generate_act_names(
            seeded_repo, backend=FakeBackend("Sorry, I can't help with that.")
        )
        assert names == {}  # nothing parsed
        assert json.loads(path.read_text()) == good  # prior names preserved

    def test_render_data_fills_persisted_name(self, seeded_repo: Path):
        data = extract_render_data(seeded_repo)
        assert data["acts"], "seeded repo should yield at least one act"
        a = data["acts"][0]
        assert a["name"] is None  # no names file yet
        sig = act_signature(a["start"], a["end"])
        (seeded_repo / ".antiquarian" / "act_names.json").write_text(
            json.dumps({sig: "The Beginning"})
        )
        refreshed = extract_render_data(seeded_repo)
        assert refreshed["acts"][0]["name"] == "The Beginning"
        # and the name reaches the rendered band, overriding the roman numeral
        assert "The Beginning" in render_acts_atom(
            refreshed["acts"], refreshed["timeline"]
        )

    def test_missing_names_file_leaves_acts_unnamed(self, seeded_repo: Path):
        data = extract_render_data(seeded_repo)
        assert all(a["name"] is None for a in data["acts"])

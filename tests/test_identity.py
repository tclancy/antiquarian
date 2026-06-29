"""Tests for .mailmap-based identity canonicalization (#118) and same-email coalescing (#147).

The renderer groups contributor lanes by email, so a person who committed
under several emails fragments into several lanes. Git's own answer is the
``.mailmap`` file; we honour it when a repo ships one. These tests pin the
four mailmap line forms (see gitmailmap(5)) and the resolution precedence.

The same-email coalescer (#147) handles the inverse: one email with two
display names (httpx's Tom Christie / Kim Christie both on
``tom@tomchristie.com``) collapses to the most-frequent display name.
"""

from __future__ import annotations

from antiquarian.identity import coalesce_by_email, parse_mailmap


class TestParseMailmapForms:
    def test_name_only_by_email_rewrites_the_name(self):
        # `Proper Name <proper@x>` — match by email, rewrite the display name.
        mm = parse_mailmap("Proper Name <proper@x>")
        assert mm.resolve("Whoever", "proper@x") == ("Proper Name", "proper@x")

    def test_email_only_rewrites_the_email_keeps_name(self):
        # `<proper@x> <commit@x>` — rewrite email, leave the name untouched.
        mm = parse_mailmap("<proper@x> <commit@x>")
        assert mm.resolve("Ada", "commit@x") == ("Ada", "proper@x")

    def test_name_and_match_email_rewrites_both(self):
        # `Proper Name <proper@x> <commit@x>`
        mm = parse_mailmap("Proper Name <proper@x> <commit@x>")
        assert mm.resolve("anything", "commit@x") == ("Proper Name", "proper@x")

    def test_full_form_requires_matching_commit_name(self):
        # `Proper Name <proper@x> Commit Name <commit@x>` only matches that name.
        mm = parse_mailmap("Proper Name <proper@x> Commit Name <commit@x>")
        assert mm.resolve("Commit Name", "commit@x") == ("Proper Name", "proper@x")
        # A different name under the same email is NOT rewritten by this rule.
        assert mm.resolve("Other Name", "commit@x") == ("Other Name", "commit@x")


class TestResolveBehaviour:
    def test_email_match_is_case_insensitive(self):
        mm = parse_mailmap("Proper Name <proper@x> <commit@x>")
        assert mm.resolve("x", "COMMIT@X") == ("Proper Name", "proper@x")

    def test_unmatched_identity_passes_through_unchanged(self):
        mm = parse_mailmap("Proper Name <proper@x> <commit@x>")
        assert mm.resolve("Stranger", "stranger@y") == ("Stranger", "stranger@y")

    def test_name_specific_rule_wins_over_email_only_rule(self):
        text = (
            "<canon@x> <shared@x>\n"
            "Special Person <special@x> Special Person <shared@x>\n"
        )
        mm = parse_mailmap(text)
        # The name-specific rule applies for that name…
        assert mm.resolve("Special Person", "shared@x") == (
            "Special Person",
            "special@x",
        )
        # …others under the same email fall to the email-only rule.
        assert mm.resolve("Someone Else", "shared@x") == ("Someone Else", "canon@x")

    def test_comments_and_blank_lines_ignored(self):
        text = "# a comment\n\nProper Name <proper@x> <commit@x>\n   \n"
        mm = parse_mailmap(text)
        assert mm.resolve("x", "commit@x") == ("Proper Name", "proper@x")

    def test_empty_mailmap_is_identity(self):
        mm = parse_mailmap("")
        assert mm.resolve("Ada", "ada@x") == ("Ada", "ada@x")


class TestCoalesceByEmail:
    """Same-email coalescer — #147 / #120 hard-signal merge."""

    def test_two_names_one_email_picks_most_frequent(self):
        # The httpx case: Tom Christie (50) + Kim Christie (1) on one email.
        pairs = [("Tom Christie", "tom@tomchristie.com")] * 50 + [
            ("Kim Christie", "tom@tomchristie.com")
        ]
        assert coalesce_by_email(pairs) == {"tom@tomchristie.com": "Tom Christie"}

    def test_single_name_per_email_not_in_mapping(self):
        # No fragmentation, no entry — callers treat missing as pass-through.
        assert coalesce_by_email([("Ada", "ada@x"), ("Bea", "bea@x")]) == {}

    def test_email_match_is_case_insensitive(self):
        pairs = [("Tom", "Tom@X"), ("Tom", "tom@x"), ("Kim", "TOM@x")]
        assert coalesce_by_email(pairs) == {"tom@x": "Tom"}

    def test_tie_break_is_lexicographic_smallest(self):
        # Two names, one commit each. Determinism > original-order luck.
        # "Adam" < "Beth" → Adam wins.
        assert coalesce_by_email([("Beth", "shared@x"), ("Adam", "shared@x")]) == {
            "shared@x": "Adam"
        }

    def test_tie_break_independent_of_input_order(self):
        forward = coalesce_by_email([("Beth", "x@x"), ("Adam", "x@x")])
        reverse = coalesce_by_email([("Adam", "x@x"), ("Beth", "x@x")])
        assert forward == reverse == {"x@x": "Adam"}

    def test_empty_input_returns_empty_mapping(self):
        assert coalesce_by_email([]) == {}

    def test_multiple_emails_independent(self):
        # Each email is resolved on its own; no cross-talk.
        pairs = (
            [("Tom", "a@x")] * 3
            + [("Kim", "a@x")]
            + [("Sam", "b@x")] * 2
            + [("Pat", "b@x")] * 5
        )
        assert coalesce_by_email(pairs) == {"a@x": "Tom", "b@x": "Pat"}

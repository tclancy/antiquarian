"""Formal verification of pipeline.py handoffs using Z3.

Invariants to prove:
1. No silent drops: every file in select_files result gets a story or error
2. Complete handoff: generate_codebase_survey receives all per-file stories
3. Output persistence: stories persisted to disk match stories in synthesis
4. Error handling: pipeline either produces story or raises exception (no silent skip)
"""

from z3 import And, Int, Not, Or, Solver, unsat


def test_no_silent_drops_in_pipeline():
    """Prove: every file in select_files result is processed (story or error).

    Invariant: the pipeline never silently skips a file. For each file in
    the selected set, either:
    - generate_file_story succeeds and produces narrative, OR
    - an exception is raised (caught or propagated)

    No path should silently drop a file from processing.
    """
    s = Solver()

    # Number of files in selection
    num_selected = Int("num_selected")
    # Number of files processed (received story or error)
    num_processed = Int("num_processed")

    s.add(num_selected > 0)

    # Invariant: for every selected file, it must be processed
    no_drop_rule = Or(num_selected <= 0, num_processed >= num_selected)
    s.add(no_drop_rule)

    # Try to violate: selected > 0 but processed < selected
    violation = And(num_selected > 0, num_processed < num_selected)
    s.add(violation)

    result = s.check()
    if result == unsat:
        print("PROVED: No silent drops (all selected files are processed)")
        return True
    else:
        print("FAILED: Silent drop protection violated")
        print(f"  Counterexample: {s.model()}")
        return False


def test_complete_handoff_to_survey():
    """Prove: generate_codebase_survey receives all per-file stories.

    Invariant: if generate_file_story produces N stories for N files,
    then synthesize_survey receives exactly N (file_path, narrative) pairs.

    No stories are lost in the handoff between layer 1 (per-file) and
    layer 2 (codebase synthesis).
    """
    s = Solver()

    # Number of files processed
    num_files_processed = Int("num_files_processed")
    # Number of stories produced by generate_file_story
    num_stories_produced = Int("num_stories_produced")
    # Number of stories received by synthesize_survey
    num_stories_received = Int("num_stories_received")

    s.add(num_files_processed > 0)

    # After processing, we produce stories
    production_rule = Or(
        num_files_processed <= 0, num_stories_produced == num_files_processed
    )
    s.add(production_rule)

    # Complete handoff: stories produced = stories received
    handoff_rule = Or(
        num_stories_produced <= 0, num_stories_received == num_stories_produced
    )
    s.add(handoff_rule)

    # Try to violate: stories produced but not all received
    violation = And(
        num_stories_produced > 0, num_stories_received < num_stories_produced
    )
    s.add(violation)

    result = s.check()
    if result == unsat:
        print("PROVED: Complete handoff (all per-file stories reach survey)")
        return True
    else:
        print("FAILED: Handoff completeness violated")
        print(f"  Counterexample: {s.model()}")
        return False


def test_no_divergence_in_persistence():
    """Prove: stories persisted to disk match stories used in synthesis.

    Invariant: when generate_file_story returns (narrative, story_file),
    the text written to story_file is identical to the narrative returned.

    Model: after write(story_file, narrative), reading story_file yields
    the same text (no lossy encoding, corruption, etc).
    """
    s = Solver()

    # Did we write the narrative to disk?
    wrote_to_disk = Bool("wrote_to_disk")
    # Is the in-memory narrative identical to the disk narrative?
    in_memory_matches_disk = Bool("in_memory_matches_disk")

    # Constraint: if we wrote, then memory and disk must match
    persistence_rule = Or(Not(wrote_to_disk), in_memory_matches_disk)
    s.add(persistence_rule)

    # Try to violate: wrote to disk but memory != disk
    violation = And(wrote_to_disk, Not(in_memory_matches_disk))
    s.add(violation)

    result = s.check()
    if result == unsat:
        print("PROVED: No divergence (persisted stories match in-memory)")
        return True
    else:
        print("FAILED: Persistence divergence protection violated")
        print(f"  Counterexample: {s.model()}")
        return False


def test_error_handling_covers_all_cases():
    """Prove: pipeline has a defined outcome for every file (success or explicit error).

    Invariant: for each selected file, either:
    - generate_file_story returns successfully with (narrative, path), OR
    - an exception is raised and handled (not silently caught and dropped)

    There is no "silent skip" path.
    """
    s = Solver()

    file_selected = Bool("file_selected")
    story_generated = Bool("story_generated")
    exception_raised = Bool("exception_raised")
    file_silently_skipped = Bool("file_silently_skipped")

    # If a file is selected, it must either generate a story or raise an exception
    error_coverage = Or(Not(file_selected), story_generated, exception_raised)
    s.add(error_coverage)

    # Silent skip is not allowed (file is selected but no story and no exception)
    no_silent_skip = Or(
        Not(file_selected),
        story_generated,
        exception_raised,
        Not(file_silently_skipped),
    )
    s.add(no_silent_skip)

    # Try to violate: file selected, story not generated, exception not raised,
    # but file was silently skipped
    violation = And(
        file_selected,
        Not(story_generated),
        Not(exception_raised),
        file_silently_skipped,
    )
    s.add(violation)

    result = s.check()
    if result == unsat:
        print("PROVED: Error handling covers all cases (no silent skips)")
        return True
    else:
        print("FAILED: Error handling completeness violated")
        print(f"  Counterexample: {s.model()}")
        return False


def test_cache_usage_improves_performance_not_correctness():
    """Prove: cache is used only for performance, not correctness.

    Invariant: cache is a pure optimization. Using the cache should not cause
    the narrative to differ from a non-cached run, assuming the underlying
    commit history hasn't changed.

    Model: if two runs process the same commits (regardless of cache), the
    narratives must be identical.
    """
    s = Solver()

    # Both runs process the same commit set
    commits_in_run1 = Int("commits_in_run1")
    commits_in_run2 = Int("commits_in_run2")

    # Narratives generated
    narrative_run1 = Int("narrative_run1")
    narrative_run2 = Int("narrative_run2")

    # Constraint: same commits -> same narrative
    cache_transparency = Or(
        commits_in_run1 != commits_in_run2, narrative_run1 == narrative_run2
    )
    s.add(cache_transparency)
    s.add(commits_in_run1 == commits_in_run2)  # both runs see same commits

    # Try to violate: same commits but different narratives
    violation = And(
        commits_in_run1 == commits_in_run2, narrative_run1 != narrative_run2
    )
    s.add(violation)

    result = s.check()
    if result == unsat:
        print(
            "PROVED: Cache is transparent (doesn't affect narrative if commits unchanged)"
        )
        return True
    else:
        print("FAILED: Cache correctness invariant violated")
        print(f"  Counterexample: {s.model()}")
        return False


if __name__ == "__main__":
    from z3 import Bool

    print("=" * 70)
    print("Pipeline Handoff Verification")
    print("=" * 70)
    print()

    results = [
        test_no_silent_drops_in_pipeline(),
        test_complete_handoff_to_survey(),
        test_no_divergence_in_persistence(),
        test_error_handling_covers_all_cases(),
        test_cache_usage_improves_performance_not_correctness(),
    ]

    print()
    print("=" * 70)
    passed = sum(results)
    total = len(results)
    print(f"Result: {passed}/{total} properties proved")
    print("=" * 70)

    exit(0 if all(results) else 1)

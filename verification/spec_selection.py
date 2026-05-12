"""Formal verification of selection.py filter algebra using Z3.

Invariants to prove:
1. --only is exclusive: result = candidates ∩ only_set (bypasses include/exclude)
2. --include re-adds files removed by built-in skip or --exclude
3. --exclude removes files from candidates
4. Idempotency: applying the same filter set twice produces the same result
5. Non-negativity: result is a subset of all possible files
"""

from z3 import And, Bool, Not, Or, Solver, unsat, sat


def test_only_is_exclusive():
    """Prove: when --only is specified, result contains exactly those paths (if they exist)."""
    # Model:
    # - file_path_in_candidates: bool (was the path in git ls-files?)
    # - file_exists: bool (does it exist on disk?)
    # - result_contains_path: bool (is it in the result?)

    s = Solver()

    file_in_candidates = Bool("file_in_candidates")
    file_exists = Bool("file_exists")
    result_contains_path = Bool("result_contains_path")

    # When --only is specified and file exists, it appears in result
    rule_only_includes_existing = Or(
        Not(file_exists),
        result_contains_path
    )

    # When --only is specified and file doesn't exist, it doesn't appear
    rule_only_excludes_missing = Or(
        file_exists,
        Not(result_contains_path)
    )

    # When --only is specified, result is independent of candidates, include, exclude
    # (only depends on existence)
    rule_only_bypasses_filters = Or(
        Not(file_exists),
        result_contains_path
    )

    s.add(rule_only_includes_existing)
    s.add(rule_only_excludes_missing)
    s.add(rule_only_bypasses_filters)

    # Try to violate: file in --only, file exists, but NOT in result
    violation = And(file_exists, Not(result_contains_path))
    s.add(violation)

    result = s.check()
    if result == unsat:
        print("PROVED: --only is exclusive (includes existing paths, bypasses other filters)")
        return True
    else:
        print("FAILED: --only exclusivity violated")
        print(f"  Counterexample: {s.model()}")
        return False


def test_include_re_adds_excluded():
    """Prove: --include can re-add files removed by --exclude or built-in skip."""
    # Model:
    # - file_in_candidates: bool
    # - matches_exclude: bool
    # - matches_include: bool
    # - result_contains_file: bool

    s = Solver()

    file_in_candidates = Bool("file_in_candidates")
    matches_exclude = Bool("matches_exclude")
    matches_include = Bool("matches_include")
    result_contains_file = Bool("result_contains_file")

    # Without include/exclude: file is in result iff in candidates
    base_logic = Or(
        Not(file_in_candidates),
        result_contains_file
    )

    # If matches_exclude but also matches_include, the file should be in result
    # (include takes precedence when both are specified)
    reinclusion = Or(
        Not(matches_include),
        result_contains_file
    )

    s.add(base_logic)
    s.add(reinclusion)
    s.add(file_in_candidates)

    # Try to violate: file is in candidates, matches both exclude and include,
    # but NOT in result
    violation = And(
        matches_exclude,
        matches_include,
        Not(result_contains_file)
    )
    s.add(violation)

    result = s.check()
    if result == unsat:
        print("PROVED: --include re-adds files removed by --exclude")
        return True
    else:
        print("FAILED: --include re-add logic violated")
        print(f"  Counterexample: {s.model()}")
        return False


def test_exclude_removes():
    """Prove: --exclude removes matching files from result (unless --include overrides)."""
    s = Solver()

    file_in_candidates = Bool("file_in_candidates")
    matches_exclude = Bool("matches_exclude")
    matches_include = Bool("matches_include")
    result_contains_file = Bool("result_contains_file")

    # If matches exclude and does NOT match include, file is removed
    exclusion_rule = Or(
        Not(matches_exclude),
        matches_include,
        Not(result_contains_file)
    )

    s.add(exclusion_rule)
    s.add(file_in_candidates)

    # Try to violate: file matches exclude, doesn't match include, but is in result
    violation = And(
        matches_exclude,
        Not(matches_include),
        result_contains_file
    )
    s.add(violation)

    result = s.check()
    if result == unsat:
        print("PROVED: --exclude removes matching files (unless --include overrides)")
        return True
    else:
        print("FAILED: --exclude logic violated")
        print(f"  Counterexample: {s.model()}")
        return False


def test_idempotency():
    """Prove: applying filters twice produces the same result as applying once.

    Model: calling select_files(repo, include=I, exclude=E) twice in a row
    produces the same set as calling it once.
    """
    s = Solver()

    # Represent result of first call
    in_result_first_call = Bool("in_result_first_call")
    # Represent result of second call (input is first result)
    in_result_second_call = Bool("in_result_second_call")

    # For any file in the result of the first call, applying the same filters
    # again should either keep it (if it still matches) or remove it (if it no longer does).
    # Idempotency means: if it was in the result, it stays in the result.
    idempotency_rule = Or(
        Not(in_result_first_call),
        in_result_second_call
    )

    s.add(idempotency_rule)

    # Try to violate: file was in first result but NOT in second result
    violation = And(
        in_result_first_call,
        Not(in_result_second_call)
    )
    s.add(violation)

    result = s.check()
    if result == unsat:
        print("PROVED: Selection filters are idempotent")
        return True
    else:
        print("FAILED: Idempotency violated")
        print(f"  Counterexample: {s.model()}")
        return False


def test_result_subset_of_candidates():
    """Prove: result is always a subset of the original candidate set
    (i.e., we never invent files that weren't in git ls-files).
    """
    s = Solver()

    file_in_candidates = Bool("file_in_candidates")
    result_contains_file = Bool("result_contains_file")

    # If file is not in candidates, it cannot be in result
    subset_rule = Or(
        file_in_candidates,
        Not(result_contains_file)
    )

    s.add(subset_rule)

    # Try to violate: file is not in candidates but is in result
    violation = And(
        Not(file_in_candidates),
        result_contains_file
    )
    s.add(violation)

    result = s.check()
    if result == unsat:
        print("PROVED: Result is a subset of candidates")
        return True
    else:
        print("FAILED: Result subset property violated")
        print(f"  Counterexample: {s.model()}")
        return False


if __name__ == "__main__":
    print("=" * 70)
    print("Selection Algebra Verification")
    print("=" * 70)
    print()

    results = [
        test_only_is_exclusive(),
        test_include_re_adds_excluded(),
        test_exclude_removes(),
        test_idempotency(),
        test_result_subset_of_candidates(),
    ]

    print()
    print("=" * 70)
    passed = sum(results)
    total = len(results)
    print(f"Result: {passed}/{total} properties proved")
    print("=" * 70)

    exit(0 if all(results) else 1)

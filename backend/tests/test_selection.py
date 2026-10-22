"""The deterministic candidate-selection rule (analysis/selection.py). Pure code; the model never chooses."""
import itertools

import pytest

from app.analysis.selection import CandidateEval, select_candidate


def ev(index, fixed, regressions, n_changed=2, grip=30.0, complete=True, targeted=50):
    return CandidateEval(index=index, fixed=fixed, targeted=targeted, regressions=regressions, n_changed=n_changed, grip_force=grip, complete=complete)


def test_picks_the_highest_targeted_fix_among_candidates_within_budget():
    assert select_candidate([ev(0, 30, 0), ev(1, 40, 2), ev(2, 35, 1)], budget=3) == 1


def test_a_better_candidate_over_budget_is_ignored():
    assert select_candidate([ev(0, 30, 0), ev(1, 49, 4), ev(2, 35, 3)], budget=3) == 2


def test_budget_boundary_is_inclusive():
    assert select_candidate([ev(0, 10, 0), ev(1, 40, 3)], budget=3) == 1   # exactly at the budget is eligible
    assert select_candidate([ev(0, 10, 0), ev(1, 40, 4)], budget=3) == 0   # one over is not


def test_tie_breaks_in_order_fewer_changed_parameters_then_lower_grip_then_lower_index():
    # equal fixed: fewer changed parameters wins
    assert select_candidate([ev(0, 40, 0, n_changed=3), ev(1, 40, 0, n_changed=1), ev(2, 40, 0, n_changed=2)], budget=3) == 1
    # equal fixed and equal n_changed: lower grip force wins
    assert select_candidate([ev(0, 40, 0, grip=60.0), ev(1, 40, 0, grip=25.0), ev(2, 40, 0, grip=45.0)], budget=3) == 1
    # everything equal: lower index wins (the rule never depends on input order)
    assert select_candidate([ev(2, 40, 0), ev(0, 40, 0), ev(1, 40, 0)], budget=3) == 0
    # fixed beats n_changed: the higher fix rate wins even with more levers
    assert select_candidate([ev(0, 39, 0, n_changed=1), ev(1, 40, 0, n_changed=4)], budget=3) == 1


def test_none_within_budget_picks_fewest_regressions_then_highest_fix():
    assert select_candidate([ev(0, 45, 6), ev(1, 20, 4), ev(2, 30, 5)], budget=3) == 1
    assert select_candidate([ev(0, 20, 4), ev(1, 30, 4), ev(2, 25, 4)], budget=3) == 1                       # tie on regressions -> higher fix
    assert select_candidate([ev(0, 30, 4, n_changed=3), ev(1, 30, 4, n_changed=1)], budget=3) == 1            # then fewer changed parameters
    assert select_candidate([ev(0, 30, 4, grip=70.0), ev(1, 30, 4, grip=35.0)], budget=3) == 1                # then lower grip


def test_incomplete_candidates_are_never_selected_and_all_incomplete_is_an_error():
    assert select_candidate([ev(0, 50, 0, complete=False), ev(1, 10, 3)], budget=3) == 1
    with pytest.raises(ValueError):
        select_candidate([ev(0, 50, 0, complete=False)], budget=3)
    with pytest.raises(ValueError):
        select_candidate([], budget=3)


def test_selection_is_independent_of_input_order():
    evals = [ev(0, 33, 1, n_changed=2, grip=40.0), ev(1, 41, 3, n_changed=3, grip=30.0), ev(2, 41, 3, n_changed=1, grip=55.0),
             ev(3, 41, 2, n_changed=1, grip=20.0), ev(4, 12, 0)]
    expected = select_candidate(evals, budget=3)
    assert expected == 3
    for perm in itertools.permutations(evals):
        assert select_candidate(list(perm), budget=3) == expected

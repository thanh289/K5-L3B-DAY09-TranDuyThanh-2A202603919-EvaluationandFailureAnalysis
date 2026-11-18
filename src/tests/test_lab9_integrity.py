"""M7 checks against report and spec tampering beyond the public trap pack."""

import copy

import pytest

from lab9.gate import integrity_check


pytestmark = pytest.mark.student


@pytest.fixture
def report():
    rows = [
        {"item_id": item, "seed": seed, "pass_rate": True,
         "slices": ["money_movement"] if item == "E-001" else []}
        for item in ("E-001", "E-002") for seed in (11, 22)
    ]
    return {"manifest": {"eval_set_sha": "same", "items": 2, "seeds": [11, 22]},
            "rows": rows, "metrics": {"pass_rate": 1.0}, "evaluator_failures": []}


@pytest.fixture
def spec():
    return {"eval_set_version": "v2",
            "metrics": [{"id": "pass_rate", "kind": "capability", "blocking": True,
                         "threshold": {"min": 0.8, "no_significant_drop": True}}],
            "slices": [{"name": "money_movement", "metric": "pass_rate", "min": 0.9,
                        "no_significant_drop": True, "blocking": True}]}


def test_duplicate_row_replacing_another_is_rejected(report, spec):
    pr = copy.deepcopy(report)
    pr["rows"][0] = copy.deepcopy(pr["rows"][1])
    assert any("duplicate" in problem for problem in integrity_check(pr, report, spec))


def test_green_run_with_evaluator_failure_is_rejected(report, spec):
    pr = copy.deepcopy(report)
    pr["evaluator_failures"] = ["E-001@11: grader crashed"]
    assert any("evaluator_failures" in problem for problem in integrity_check(pr, report, spec))


def test_relabelled_slice_is_rejected(report, spec):
    pr = copy.deepcopy(report)
    pr["rows"][0]["slices"] = []
    assert any("slice tags changed" in problem for problem in integrity_check(pr, report, spec))


def test_forged_aggregate_is_rejected(report, spec):
    pr = copy.deepcopy(report)
    pr["rows"][0]["pass_rate"] = False
    assert any("disagrees with rows" in problem for problem in integrity_check(pr, report, spec))


def test_ratchet_rejects_removed_metric_and_slice(report, spec):
    loose = copy.deepcopy(spec)
    loose["metrics"] = []
    loose["slices"] = []
    problems = integrity_check(report, report, loose, spec)
    assert any("removed metrics" in problem for problem in problems)
    assert any("removed slices" in problem for problem in problems)


def test_ratchet_rejects_dropped_significance_check(report, spec):
    loose = copy.deepcopy(spec)
    loose["metrics"][0]["threshold"].pop("no_significant_drop")
    loose["slices"][0].pop("no_significant_drop")
    problems = integrity_check(report, report, loose, spec)
    assert sum("removed no_significant_drop" in problem for problem in problems) == 2

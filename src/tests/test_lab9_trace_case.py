"""Regression evidence for the first wrong step in C-002@11."""

from types import SimpleNamespace

import pytest

from lab9.graders import DbFactKept, RefundAmountCorrect
from lab9.trace_case import investigate


pytestmark = pytest.mark.student


def test_c002_ticket_delay_must_not_override_database():
    broken = investigate("seeded_regression", "C-002", 11)
    fixed = investigate("fixed", "C-002", 11)
    bad_trial, good_trial = broken["trial"], fixed["trial"]

    # The investigator observed the authoritative two-day delay before the
    # variant substituted the ticket's five-day claim.
    assert bad_trial["events"][1]["payload"]["lookup_order"]["order"]["delay_days"] == 2
    assert bad_trial["events"][2]["kind"] == "model_override"
    assert bad_trial["events"][2]["payload"]["delay_days"] == 5
    assert all(event["kind"] != "model_override" for event in good_trial["events"])

    bad_ctx = SimpleNamespace(output=bad_trial, expected_output=broken["label"])
    good_ctx = SimpleNamespace(output=good_trial, expected_output=fixed["label"])
    assert DbFactKept().evaluate(bad_ctx).value is False
    assert DbFactKept().evaluate(good_ctx).value is True
    assert RefundAmountCorrect().evaluate(bad_ctx).value is False
    assert RefundAmountCorrect().evaluate(good_ctx).value is True
    assert bad_trial["snapshot"]["refund_vnd"] == 20000
    assert good_trial["snapshot"]["refund_vnd"] == 0

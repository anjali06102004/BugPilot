from __future__ import annotations

from bugpilot_core.models import FindingCandidate, FindingCategory
from bugpilot_core.verification import (
    evaluate_verification,
    matches_issue,
    normalise,
)


def candidate(**overrides) -> FindingCandidate:
    data = dict(
        category=FindingCategory.OVERFLOW,
        title="Horizontal overflow on page",
        description="wide",
        confidence=0.95,
        source="overflow_detector",
        url="https://shop.example.com/cart",
        fingerprint="fp-overflow",
        error_signature="h-overflow:390",
    )
    data.update(overrides)
    return FindingCandidate(**data)


def evaluate(**overrides):
    data = dict(
        candidates_after=[candidate()],
        issue_snapshot={
            "error_signature": "h-overflow:390",
            "fingerprint": "fp-overflow",
            "selector": None,
            "title": "Horizontal overflow on page",
        },
        page_loaded=True,
        replay_failures=0,
        element_required=False,
        element_found=True,
    )
    data.update(overrides)
    return evaluate_verification(**data)


def test_still_failing_when_signal_persists():
    verdict, reason = evaluate()
    assert verdict == "still_failing"
    assert "still present" in reason


def test_fixed_only_when_replay_completed_and_signal_gone():
    verdict, reason = evaluate(candidates_after=[])
    assert verdict == "fixed"
    assert "signal is gone" in reason


def test_page_not_loaded_is_inconclusive():
    verdict, reason = evaluate(candidates_after=[], page_loaded=False)
    assert verdict == "inconclusive"
    assert "could not be loaded" in reason


def test_missing_element_is_inconclusive_not_fixed():
    verdict, reason = evaluate(
        candidates_after=[],
        element_required=True,
        element_found=False,
    )
    assert verdict == "inconclusive"
    assert "no longer exists" in reason


def test_replay_failure_is_inconclusive():
    verdict, reason = evaluate(candidates_after=[], replay_failures=2)
    assert verdict == "inconclusive"
    assert "replay step" in reason


def test_http_success_alone_never_means_fixed():
    # Page loaded fine but the detector still sees the defect.
    verdict, _ = evaluate(page_loaded=True)
    assert verdict == "still_failing"


def test_matches_by_normalised_signature():
    issue = {"error_signature": "h-overflow:390"}
    match = matches_issue(issue, [candidate(error_signature="h-overflow:375")])
    assert match is not None


def test_matches_by_fingerprint_and_selector_and_title():
    assert matches_issue({"fingerprint": "fp-overflow"}, [candidate()])
    assert matches_issue({"selector": "div.wide"}, [candidate(selector="div.wide")])
    assert matches_issue({"title": "Horizontal overflow on page"}, [candidate()])
    assert matches_issue({"title": "Something else entirely"}, [candidate()]) is None


def test_normalise_collapses_numbers_and_punctuation():
    assert normalise("HTTP 500 on GET /api/orders/123") == normalise("HTTP 404 on GET /api/orders/999")
    assert normalise(None) == ""

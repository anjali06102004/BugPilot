from __future__ import annotations

from bugpilot_core.models import FindingCategory
from bugpilot_core.registry import (
    ALLOWED_TRANSITIONS,
    can_transition,
    issue_key,
    normalize_signature,
    route_of,
)


def test_issue_key_is_stable_across_scans():
    from bugpilot_core.models import FindingCandidate

    a = FindingCandidate(
        category=FindingCategory.BROKEN_IMAGE,
        title="Broken image",
        description="x",
        confidence=0.9,
        source="broken_images_detector",
        url="https://shop.example.com/cart?step=1",
        fingerprint="fp-1",
        error_signature="broken-img:/missing.png",
    )
    b = a.model_copy(update={"url": "https://shop.example.com/cart?step=2", "description": "changed copy"})
    assert issue_key(a, project_id="p1") == issue_key(b, project_id="p1")
    assert issue_key(a, project_id="p1") != issue_key(a, project_id="p2")


def test_issue_key_differs_for_distinct_defects():
    from bugpilot_core.models import FindingCandidate

    base = dict(
        category=FindingCategory.ACCESSIBILITY,
        description="x",
        confidence=0.9,
        source="accessibility_detector",
        url="https://shop.example.com/",
    )
    a = FindingCandidate(title="Image missing alt text", fingerprint="img-1", **base)
    b = FindingCandidate(title="Image missing alt text", fingerprint="img-2", **base)
    assert issue_key(a, project_id="p1") != issue_key(b, project_id="p1")


def test_route_of_strips_query_and_host():
    assert route_of("https://shop.example.com/checkout?step=2#pay") == "/checkout"
    assert route_of("https://shop.example.com") == "/"


def test_normalize_signature_collapses_numbers():
    assert normalize_signature("HTTP 500 on GET /api/orders/123") == normalize_signature(
        "HTTP 404 on GET /api/orders/999"
    )
    assert normalize_signature(None) == ""


def test_lifecycle_happy_path_is_allowed():
    path = ["new", "triaged", "confirmed", "in_progress", "fixed", "verified", "closed"]
    for current, target in zip(path, path[1:], strict=False):
        assert can_transition(current, target), f"{current} -> {target} should be allowed"


def test_invalid_lifecycle_transitions_are_rejected():
    assert not can_transition("new", "verified")
    assert not can_transition("verified", "in_progress")
    assert not can_transition("closed", "confirmed")
    assert not can_transition("duplicate", "verified")


def test_terminal_states_can_reopen():
    assert can_transition("closed", "reopened")
    assert can_transition("fixed", "reopened")


def test_every_transition_target_is_a_known_status():
    from bugpilot_core.models import IssueStatus

    known = {status.value for status in IssueStatus}
    for status, targets in ALLOWED_TRANSITIONS.items():
        assert status.value if hasattr(status, "value") else status in known
        for target in targets:
            assert target.value in known

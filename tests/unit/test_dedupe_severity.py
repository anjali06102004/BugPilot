from bugpilot_core.dedupe import dedupe_candidates
from bugpilot_core.models import FindingCandidate, FindingCategory
from bugpilot_core.severity import score_severity


def test_dedupe_merges_same_issue():
    a = FindingCandidate(
        category=FindingCategory.OVERFLOW,
        title="Horizontal overflow on page",
        description="wide",
        confidence=0.8,
        source="overflow_detector",
        url="https://example.com/",
        error_signature="h-overflow:390",
    )
    b = FindingCandidate(
        category=FindingCategory.OVERFLOW,
        title="Horizontal overflow on page",
        description="still wide",
        confidence=0.95,
        source="overflow_detector",
        url="https://example.com/",
        error_signature="h-overflow:390",
    )
    merged = dedupe_candidates([a, b])
    assert len(merged) == 1
    assert merged[0].confidence == 0.95


def test_severity_network_500():
    candidate = FindingCandidate(
        category=FindingCategory.NETWORK,
        title="HTTP 500",
        description="fail",
        confidence=0.93,
        source="network_detector",
        url="https://example.com/",
        metadata={"status": 500},
    )
    assert score_severity(candidate, reproduced=True).value == "high"

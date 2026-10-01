from bugpilot_core.detectors.base import PageSnapshot, candidate
from bugpilot_core.models import FindingCandidate, FindingCategory


def detect_navigation(snapshot: PageSnapshot, previous_url: str | None) -> list[FindingCandidate]:
    if not previous_url:
        return []
    findings: list[FindingCandidate] = []
    if snapshot.url in {"", "about:blank"}:
        findings.append(
            candidate(
                snapshot,
                category=FindingCategory.NAVIGATION,
                title="Navigation left a blank page",
                description="An action navigated to about:blank or an empty document.",
                source="navigation_detector",
                confidence=0.8,
                expected="Navigation lands on a meaningful application URL.",
                actual=snapshot.url,
                error_signature="nav:blank",
                metadata={"workflow_impact": 0.9},
            )
        )
    return findings

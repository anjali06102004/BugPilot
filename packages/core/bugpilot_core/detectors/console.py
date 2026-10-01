from bugpilot_core.detectors.base import PageSnapshot, candidate
from bugpilot_core.models import FindingCandidate, FindingCategory


def detect_console(snapshot: PageSnapshot) -> list[FindingCandidate]:
    findings: list[FindingCandidate] = []
    for event in snapshot.console:
        if event.level not in {"error", "pageerror"}:
            continue
        findings.append(
            candidate(
                snapshot,
                category=FindingCategory.CONSOLE,
                title="Browser console error",
                description=event.text[:500],
                source="console_detector",
                confidence=0.9,
                expected="Page scripts run without uncaught errors.",
                actual=event.text[:500],
                error_signature=f"console:{event.text[:180]}",
                metadata={"level": event.level, "user_impact": 0.5, "workflow_impact": 0.4},
            )
        )
    return findings

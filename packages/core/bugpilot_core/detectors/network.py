from bugpilot_core.detectors.base import PageSnapshot, candidate
from bugpilot_core.models import FindingCandidate, FindingCategory


def detect_network(snapshot: PageSnapshot) -> list[FindingCandidate]:
    findings: list[FindingCandidate] = []
    for event in snapshot.network:
        status = event.status or 0
        failed = event.failed or status >= 400
        if not failed:
            continue
        if status in {0} and not event.failed:
            continue
        title = f"HTTP {status} on {event.method} request" if status else "Network request failed"
        findings.append(
            candidate(
                snapshot,
                category=FindingCategory.NETWORK,
                title=title,
                description=f"{event.method} {event.url} failed ({status or event.failure_text}).",
                source="network_detector",
                confidence=0.93 if status >= 500 else 0.84,
                expected="API and asset requests succeed or the UI explains the failure.",
                actual=f"status={status} failed={event.failed}",
                error_signature=f"net:{event.method}:{status}:{event.url.split('?')[0]}",
                metadata={
                    "status": status,
                    "user_impact": 0.7 if status >= 500 else 0.5,
                    "workflow_impact": 0.8 if status >= 500 else 0.4,
                },
            )
        )
    return findings

from bugpilot_core.detectors.base import PageSnapshot, candidate
from bugpilot_core.models import FindingCandidate, FindingCategory


def detect_overflow(snapshot: PageSnapshot) -> list[FindingCandidate]:
    findings: list[FindingCandidate] = []
    horizontal = snapshot.scroll_width > snapshot.client_width + 2
    if horizontal:
        findings.append(
            candidate(
                snapshot,
                category=FindingCategory.OVERFLOW,
                title="Horizontal overflow on page",
                description=(
                    f"The document scroll width ({snapshot.scroll_width:.0f}px) exceeds the "
                    f"viewport width ({snapshot.client_width:.0f}px)."
                ),
                source="overflow_detector",
                confidence=0.95,
                expected="Page content fits within the viewport without horizontal scrolling.",
                actual=f"scrollWidth={snapshot.scroll_width:.0f}, clientWidth={snapshot.client_width:.0f}",
                error_signature=f"h-overflow:{snapshot.viewport.width}",
                metadata={"horizontal": True, "user_impact": 0.75, "workflow_impact": 0.4},
            )
        )
    overflowing = [
        el
        for el in snapshot.elements
        if el.visible
        and el.styles.get("overflow") in {"visible", "", None}
        and el.box
        and el.box.width > snapshot.client_width + 8
        and el.tag not in {"html", "body"}
    ]
    for el in overflowing[:8]:
        findings.append(
            candidate(
                snapshot,
                category=FindingCategory.OVERFLOW,
                title=f"Element wider than viewport: {el.tag}",
                description=f"{el.selector} is {el.box.width:.0f}px wide in a {snapshot.client_width:.0f}px viewport.",
                source="overflow_detector",
                confidence=0.86,
                selector=el.selector,
                fingerprint=el.fingerprint,
                expected="Elements should wrap or shrink to the viewport.",
                actual=f"width={el.box.width:.0f}px",
                error_signature=f"el-overflow:{el.fingerprint}",
                metadata={"horizontal": True},
            )
        )
    return findings

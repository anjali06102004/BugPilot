from bugpilot_core.detectors.base import PageSnapshot, boxes_intersect, candidate, parent_child
from bugpilot_core.models import FindingCandidate, FindingCategory

SKIP_TAGS = {"html", "body", "script", "style", "head", "meta", "link"}


def detect_layout(snapshot: PageSnapshot) -> list[FindingCandidate]:
    findings: list[FindingCandidate] = []
    visible = [
        el
        for el in snapshot.elements
        if el.visible
        and el.box
        and el.box.width >= 12
        and el.box.height >= 12
        and el.tag not in SKIP_TAGS
        and el.interactive
    ]
    for i, a in enumerate(visible):
        for b in visible[i + 1 :]:
            if parent_child(a, b):
                continue
            area = boxes_intersect(a.box, b.box, min_area=40)
            if area < 40:
                continue
            smaller = min(a.box.width * a.box.height, b.box.width * b.box.height)
            if smaller <= 0 or area / smaller < 0.18:
                continue
            findings.append(
                candidate(
                    snapshot,
                    category=FindingCategory.LAYOUT,
                    title="Interactive elements overlap",
                    description=(
                        f"{a.tag} '{a.text[:40]}' overlaps {b.tag} '{b.text[:40]}' "
                        f"by {area:.0f}px²."
                    ),
                    source="layout_detector",
                    confidence=0.91,
                    selector=a.selector,
                    fingerprint=f"{a.fingerprint}+{b.fingerprint}",
                    expected="Interactive controls remain separated and independently clickable.",
                    actual=f"Overlap area {area:.0f}px² between {a.selector} and {b.selector}",
                    error_signature=f"overlap:{a.fingerprint}:{b.fingerprint}",
                    metadata={"user_impact": 0.8, "workflow_impact": 0.7, "overlap_area": area},
                )
            )
    clipped = [
        el
        for el in snapshot.elements
        if el.visible
        and el.box
        and el.interactive
        and (
            el.box.x + el.box.width < 4
            or el.box.y + el.box.height < 4
            or el.box.x > snapshot.viewport.width - 4
            or el.styles.get("text-overflow") == "clip"
        )
    ]
    for el in clipped[:6]:
        findings.append(
            candidate(
                snapshot,
                category=FindingCategory.VISUAL,
                title="Interactive control appears clipped",
                description=f"{el.selector} may be clipped or positioned outside the usable viewport.",
                source="layout_detector",
                confidence=0.72,
                selector=el.selector,
                fingerprint=el.fingerprint,
                expected="Controls remain fully visible.",
                actual=f"box=({el.box.x:.0f},{el.box.y:.0f},{el.box.width:.0f}x{el.box.height:.0f})",
            )
        )
    return findings

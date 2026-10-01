from bugpilot_core.detectors.base import PageSnapshot, candidate
from bugpilot_core.models import FindingCandidate, FindingCategory


def detect_broken_images(snapshot: PageSnapshot) -> list[FindingCandidate]:
    findings: list[FindingCandidate] = []
    for el in snapshot.elements:
        if el.tag != "img":
            continue
        broken = el.attributes.get("naturalWidth") == "0" or el.attributes.get("broken") == "true"
        if not broken:
            continue
        findings.append(
            candidate(
                snapshot,
                category=FindingCategory.BROKEN_IMAGE,
                title="Broken image",
                description=f"Image failed to load: {el.attributes.get('src', el.selector)}",
                source="broken_images_detector",
                confidence=0.97,
                selector=el.selector,
                fingerprint=el.fingerprint,
                expected="Images load and render at a non-zero size.",
                actual="naturalWidth=0",
                error_signature=f"broken-img:{el.attributes.get('src', '')}",
                metadata={"user_impact": 0.6},
            )
        )
    return findings

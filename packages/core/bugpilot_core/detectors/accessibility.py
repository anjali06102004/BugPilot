from bugpilot_core.detectors.base import PageSnapshot, candidate
from bugpilot_core.models import FindingCandidate, FindingCategory

LABELABLE = {"input", "select", "textarea"}


def detect_accessibility(snapshot: PageSnapshot) -> list[FindingCandidate]:
    findings: list[FindingCandidate] = []
    if not snapshot.html_lang:
        findings.append(
            candidate(
                snapshot,
                category=FindingCategory.ACCESSIBILITY,
                title="Missing html lang attribute",
                description="The root document does not declare a language.",
                source="accessibility_detector",
                confidence=0.88,
                expected="<html lang='...'> is present.",
                actual="html lang is empty",
                error_signature="a11y:html-lang",
                metadata={"accessibility_impact": 0.5},
            )
        )

    headings = [el for el in snapshot.elements if el.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}]
    last_level = 0
    for el in headings:
        level = int(el.tag[1])
        if last_level and level > last_level + 1:
            findings.append(
                candidate(
                    snapshot,
                    category=FindingCategory.ACCESSIBILITY,
                    title="Skipped heading level",
                    description=f"Heading jumps from h{last_level} to {el.tag}.",
                    source="accessibility_detector",
                    confidence=0.8,
                    selector=el.selector,
                    fingerprint=el.fingerprint,
                    error_signature=f"a11y:heading:{el.fingerprint}",
                    metadata={"accessibility_impact": 0.45},
                )
            )
        last_level = level

    for el in snapshot.elements:
        if el.tag == "img" and el.attributes.get("alt") is None and el.attributes.get("role") != "presentation":
            findings.append(
                candidate(
                    snapshot,
                    category=FindingCategory.ACCESSIBILITY,
                    title="Image missing alt text",
                    description=f"Image {el.attributes.get('src', el.selector)} has no alt attribute.",
                    source="accessibility_detector",
                    confidence=0.92,
                    selector=el.selector,
                    fingerprint=el.fingerprint,
                    expected="Informative images have alt text; decorative images have empty alt or role=presentation.",
                    actual="alt attribute missing",
                    error_signature=f"a11y:alt:{el.fingerprint}",
                    metadata={"accessibility_impact": 0.7},
                )
            )
        if el.tag in LABELABLE and el.attributes.get("type") != "hidden":
            has_label = bool(
                el.attributes.get("aria-label")
                or el.attributes.get("aria-labelledby")
                or el.attributes.get("labeled") == "true"
            )
            if not has_label:
                findings.append(
                    candidate(
                        snapshot,
                        category=FindingCategory.ACCESSIBILITY,
                        title="Form control missing accessible name",
                        description=f"{el.tag} {el.selector} has no associated label.",
                        source="accessibility_detector",
                        confidence=0.9,
                        selector=el.selector,
                        fingerprint=el.fingerprint,
                        expected="Every input has a label or aria-label.",
                        actual="No accessible name",
                        error_signature=f"a11y:label:{el.fingerprint}",
                        metadata={"accessibility_impact": 0.8, "workflow_impact": 0.5},
                    )
                )
        if el.tag == "button" and not (el.text.strip() or el.attributes.get("aria-label")):
            findings.append(
                candidate(
                    snapshot,
                    category=FindingCategory.ACCESSIBILITY,
                    title="Button missing accessible name",
                    description=f"Button {el.selector} has no text or aria-label.",
                    source="accessibility_detector",
                    confidence=0.9,
                    selector=el.selector,
                    fingerprint=el.fingerprint,
                    error_signature=f"a11y:button-name:{el.fingerprint}",
                    metadata={"accessibility_impact": 0.75},
                )
            )
    return findings

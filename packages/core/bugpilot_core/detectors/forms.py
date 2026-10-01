from bugpilot_core.detectors.base import PageSnapshot, candidate
from bugpilot_core.models import FindingCandidate, FindingCategory


def detect_forms(snapshot: PageSnapshot) -> list[FindingCandidate]:
    findings: list[FindingCandidate] = []
    for el in snapshot.elements:
        if el.tag != "form":
            continue
        required = el.attributes.get("hasRequired") == "true"
        novalidate = el.attributes.get("novalidate") == "true"
        if required and novalidate:
            findings.append(
                candidate(
                    snapshot,
                    category=FindingCategory.FORMS,
                    title="Required form disables native validation",
                    description="A form with required fields uses novalidate, so the browser will not check them.",
                    source="forms_detector",
                    confidence=0.7,
                    selector=el.selector,
                    fingerprint=el.fingerprint,
                    expected="Required fields are validated before submit.",
                    actual="novalidate is set on a form with required fields",
                    error_signature=f"form:novalidate:{el.fingerprint}",
                )
            )
    return findings

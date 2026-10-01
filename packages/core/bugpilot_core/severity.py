from __future__ import annotations

from bugpilot_core.models import FindingCandidate, FindingCategory, SeverityLevel

HIGH_IMPACT = {
    FindingCategory.NETWORK,
    FindingCategory.FUNCTIONAL,
    FindingCategory.NAVIGATION,
    FindingCategory.FORMS,
}
A11Y_HIGH = {"missing-label", "keyboard", "contrast"}


def score_severity(candidate: FindingCandidate, *, reproduced: bool) -> SeverityLevel:
    category = candidate.category
    meta = candidate.metadata
    impact = float(meta.get("user_impact", 0.5))
    workflow = float(meta.get("workflow_impact", 0.4))
    data_impact = float(meta.get("data_impact", 0.0))
    scope = float(meta.get("scope", 0.3))
    frequency = float(meta.get("frequency", 0.5))
    a11y = float(meta.get("accessibility_impact", 0.0))
    reproducibility = 0.9 if reproduced else 0.4

    if category in HIGH_IMPACT and candidate.confidence >= 0.8:
        workflow = max(workflow, 0.8)
    if category == FindingCategory.ACCESSIBILITY:
        a11y = max(a11y, 0.7)
    if category == FindingCategory.OVERFLOW and meta.get("horizontal"):
        impact = max(impact, 0.7)

    raw = (
        0.22 * impact
        + 0.22 * workflow
        + 0.12 * data_impact
        + 0.1 * scope
        + 0.1 * frequency
        + 0.14 * reproducibility
        + 0.1 * a11y
    )
    if category == FindingCategory.NETWORK and (meta.get("status") or 0) >= 500:
        return SeverityLevel.HIGH if reproduced else SeverityLevel.MEDIUM
    if raw >= 0.85:
        return SeverityLevel.CRITICAL
    if raw >= 0.68:
        return SeverityLevel.HIGH
    if raw >= 0.5:
        return SeverityLevel.MEDIUM
    if raw >= 0.32:
        return SeverityLevel.LOW
    return SeverityLevel.INFORMATIONAL

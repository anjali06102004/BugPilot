from __future__ import annotations

from dataclasses import dataclass, field

from bugpilot_core.models import (
    ConfidenceLabel,
    FindingCandidate,
    FindingCategory,
    PriorityLevel,
    SeverityLevel,
)

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


@dataclass
class PrioritySignals:
    """Inputs that drive priority, kept separate from severity inputs."""

    severity: SeverityLevel
    confidence: ConfidenceLabel
    blocks_critical_flow: bool = False
    on_critical_route: bool = False
    regression: bool = False
    occurrence_count: int = 1
    affected_pages: int = 1
    data_risk: bool = False
    accessibility: bool = False
    workaround_exists: bool = True
    user_reachable: bool = True


@dataclass
class PriorityResult:
    priority: PriorityLevel
    rationale: list[str] = field(default_factory=list)


def score_priority(candidate: FindingCandidate, signals: PrioritySignals) -> PriorityResult:
    """Explainable priority score.

    Priority answers "how soon must this be fixed", which is a different
    question from severity ("how bad is it"). Business context, reach and
    urgency are only known here, so they never leak into the severity score.
    """
    rationale: list[str] = []
    score = 0.0

    severity_points = {
        SeverityLevel.CRITICAL: 0.62,
        SeverityLevel.HIGH: 0.48,
        SeverityLevel.MEDIUM: 0.34,
        SeverityLevel.LOW: 0.18,
        SeverityLevel.INFORMATIONAL: 0.04,
    }
    score += severity_points[signals.severity]
    rationale.append(f"severity {signals.severity.value} contributes {severity_points[signals.severity]:.2f}")

    # Priority is about urgency, so evidence strength moves it: a confirmed
    # defect deserves a faster response than an unverified hypothesis of the
    # same severity.
    if signals.confidence == ConfidenceLabel.CONFIRMED:
        score += 0.2
        rationale.append("confirmed by evidence (+0.20)")
    elif signals.confidence == ConfidenceLabel.LIKELY:
        score += 0.1
        rationale.append("likely from evidence (+0.10)")

    if signals.blocks_critical_flow:
        score += 0.25
        rationale.append("blocks a critical user flow (+0.25)")
    if signals.on_critical_route:
        score += 0.15
        rationale.append("route is marked business-critical (+0.15)")
    if signals.regression:
        score += 0.15
        rationale.append("regression of a previously fixed issue (+0.15)")
    if signals.data_risk:
        score += 0.12
        rationale.append("possible data loss or corruption (+0.12)")
    if signals.accessibility:
        score += 0.08
        rationale.append("accessibility impact (+0.08)")
    if not signals.workaround_exists:
        score += 0.12
        rationale.append("no workaround available (+0.12)")
    if signals.affected_pages > 1:
        reach = min(0.12, 0.04 * signals.affected_pages)
        score += reach
        rationale.append(f"seen on {signals.affected_pages} pages (+{reach:.2f})")
    if signals.occurrence_count > 1:
        recurrence = min(0.1, 0.02 * signals.occurrence_count)
        score += recurrence
        rationale.append(f"recurred {signals.occurrence_count} times (+{recurrence:.2f})")
    if not signals.user_reachable:
        score -= 0.15
        rationale.append("not reachable by end users (-0.15)")

    # An unconfirmed hypothesis never escalates to an urgent priority.
    if signals.confidence in {ConfidenceLabel.POSSIBLE, ConfidenceLabel.NOT_A_BUG}:
        score = min(score, 0.5)
        rationale.append("confidence is not strong enough to escalate priority")

    if score >= 0.85:
        priority = PriorityLevel.P0
    elif score >= 0.62:
        priority = PriorityLevel.P1
    elif score >= 0.36:
        priority = PriorityLevel.P2
    else:
        priority = PriorityLevel.P3
    rationale.append(f"total {score:.2f} → {priority.value}")
    return PriorityResult(priority=priority, rationale=rationale)

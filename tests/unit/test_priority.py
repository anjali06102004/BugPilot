from __future__ import annotations

from bugpilot_core.models import (
    ConfidenceLabel,
    FindingCandidate,
    FindingCategory,
    PriorityLevel,
    SeverityLevel,
)
from bugpilot_core.severity import PrioritySignals, score_priority, score_severity


def candidate(**overrides) -> FindingCandidate:
    data = dict(
        category=FindingCategory.OVERFLOW,
        title="Horizontal overflow on page",
        description="wide",
        confidence=0.95,
        source="overflow_detector",
        url="https://shop.example.com/",
        metadata={"horizontal": True, "user_impact": 0.8, "workflow_impact": 0.6, "scope": 0.5},
    )
    data.update(overrides)
    return FindingCandidate(**data)


def signals(**overrides) -> PrioritySignals:
    data = dict(
        severity=SeverityLevel.MEDIUM,
        confidence=ConfidenceLabel.CONFIRMED,
    )
    data.update(overrides)
    return PrioritySignals(**data)


def test_severity_and_priority_are_separate_concepts():
    item = candidate()
    severity = score_severity(item, reproduced=True)
    priority = score_priority(item, signals(severity=severity))
    # Same evidence, but priority adds urgency on a critical route.
    urgent = score_priority(
        item,
        signals(severity=severity, on_critical_route=True, blocks_critical_flow=True),
    )
    assert severity == SeverityLevel.MEDIUM
    assert priority.priority == PriorityLevel.P2
    assert urgent.priority in {PriorityLevel.P0, PriorityLevel.P1}
    assert urgent.priority.value != priority.priority.value


def test_critical_route_and_critical_flow_escalate():
    item = candidate(category=FindingCategory.FUNCTIONAL, metadata={"workflow_impact": 0.9})
    severity = score_severity(item, reproduced=True)
    result = score_priority(
        item,
        signals(
            severity=severity,
            on_critical_route=True,
            blocks_critical_flow=True,
        ),
    )
    assert result.priority in {PriorityLevel.P0, PriorityLevel.P1}
    assert any("business-critical" in reason for reason in result.rationale)


def test_unconfirmed_hypothesis_cannot_be_urgent():
    item = candidate()
    result = score_priority(
        item,
        signals(
            severity=SeverityLevel.CRITICAL,
            confidence=ConfidenceLabel.POSSIBLE,
            on_critical_route=True,
            blocks_critical_flow=True,
            data_risk=True,
        ),
    )
    assert result.priority in {PriorityLevel.P2, PriorityLevel.P3}
    assert any("not strong enough" in reason for reason in result.rationale)


def test_regression_and_recurrence_raise_priority():
    item = candidate()
    base = score_priority(item, signals(severity=SeverityLevel.LOW))
    regression = score_priority(
        item,
        signals(severity=SeverityLevel.LOW, regression=True, occurrence_count=5, affected_pages=4),
    )
    assert regression.priority.value <= base.priority.value
    assert any("regression" in reason for reason in regression.rationale)


def test_rationale_is_explainable():
    result = score_priority(candidate(), signals())
    assert result.rationale
    assert any("severity" in reason for reason in result.rationale)
    assert any("total" in reason for reason in result.rationale)


def test_severity_network_500_high_when_reproduced():
    item = candidate(
        category=FindingCategory.NETWORK,
        title="HTTP 500",
        metadata={"status": 500, "user_impact": 0.7, "workflow_impact": 0.8},
    )
    assert score_severity(item, reproduced=True) == SeverityLevel.HIGH
    assert score_severity(item, reproduced=False) == SeverityLevel.MEDIUM

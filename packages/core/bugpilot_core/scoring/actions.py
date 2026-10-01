from __future__ import annotations

from bugpilot_core.models import ActionType, DomElement, PlannedAction

IMPORTANT_ROLES = {"link", "button", "textbox", "searchbox", "combobox", "menuitem"}
IMPORTANT_WORDS = ("nav", "menu", "search", "login", "sign", "cart", "product", "form", "submit")


def score_action(
    action: PlannedAction,
    element: DomElement | None,
    *,
    seen_fingerprints: set[str],
    visited_urls: set[str],
) -> PlannedAction:
    text = (element.text if element else action.description).lower()
    fingerprint = action.fingerprint or (element.fingerprint if element else "")

    novelty = 1.0
    if fingerprint and fingerprint in seen_fingerprints:
        novelty = 0.15
    if action.url and action.url in visited_urls:
        novelty = min(novelty, 0.35)

    importance = 0.4
    if element and (element.role in IMPORTANT_ROLES or element.interactive):
        importance += 0.25
    if any(word in text for word in IMPORTANT_WORDS):
        importance += 0.2
    if action.type in {ActionType.SUBMIT_FORM, ActionType.FILL}:
        importance += 0.15

    interaction_probability = 0.5
    if element and element.visible and element.interactive and not element.disabled:
        interaction_probability = 0.9

    bug_value = 0.4
    if action.type in {ActionType.FILL, ActionType.SUBMIT_FORM, ActionType.RESIZE}:
        bug_value += 0.3
    if "menu" in text or "nav" in text:
        bug_value += 0.15

    already_tested_penalty = 0.0 if novelty > 0.5 else 0.6
    risk = 0.1
    if action.blocked_by_policy:
        risk = 1.0
        already_tested_penalty = 1.0

    score = (
        novelty
        + importance
        + interaction_probability
        + bug_value
        - risk
        - already_tested_penalty
    )
    action.novelty = novelty
    action.importance = importance
    action.interaction_probability = interaction_probability
    action.bug_value = bug_value
    action.risk = risk
    action.already_tested_penalty = already_tested_penalty
    action.score = round(score, 4)
    return action

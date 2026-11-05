"""Server-side enforcement of the user-selected scan scope.

The scope is a hard boundary, not a hint. Every navigation and every browser
action is checked here before it is executed, so the model cannot widen the
scope by reasoning its way there.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bugpilot_core.models import ActionType, InteractionDepth, PlannedAction, ScanScope, ScopeType


@dataclass
class ScopeDecision:
    allowed: bool
    reason: str = ""


@dataclass
class ScopeGuard:
    """Tracks the live position of a scan inside its authorized scope."""

    scope: ScanScope
    origin: str = ""
    start_url: str = ""
    depth: int = 0
    max_depth: int = 3
    _skipped: list[tuple[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.origin = self.scope.origin()
        self.start_url = self.scope.start_url
        self.max_depth = self.scope.max_depth

    # -- helpers ---------------------------------------------------------
    @property
    def skipped(self) -> list[tuple[str, str]]:
        return list(self._skipped)

    def _skip(self, url: str, reason: str) -> None:
        self._skipped.append((url, reason))

    @staticmethod
    def _normalize(url: str) -> str:
        parsed = urlparse(url)
        return parsed._replace(fragment="").geturl()

    def _same_origin(self, url: str) -> bool:
        return urlparse(url).netloc.lower() == self.origin

    def _matches_patterns(self, url: str) -> bool:
        for pattern in self.scope.exclude_patterns:
            if fnmatch.fnmatch(url, pattern) or pattern in url:
                return False
        if self.scope.include_patterns:
            return any(fnmatch.fnmatch(url, pattern) for pattern in self.scope.include_patterns)
        return True

    # -- checks ----------------------------------------------------------
    def check_navigation(self, current_url: str, target_url: str) -> ScopeDecision:
        """May the browser navigate from current_url to target_url?"""
        target = self._normalize(target_url)
        current = self._normalize(current_url)

        if self.scope.type == ScopeType.SINGLE_URL:
            if target == self._normalize(self.start_url):
                return ScopeDecision(True)
            return ScopeDecision(False, "Single URL scans may only inspect the selected URL.")

        if self.scope.type == ScopeType.SELECTED_ELEMENT:
            if target == self._normalize(self.start_url):
                return ScopeDecision(True)
            return ScopeDecision(
                False, "Selected element scans may not navigate away from the inspected page."
            )

        # Full site scans
        if not self._same_origin(target):
            self._skip(target, "outside the authorized origin")
            return ScopeDecision(False, "Target is outside the authorized origin.")
        if not self._matches_patterns(target):
            self._skip(target, "excluded by URL pattern")
            return ScopeDecision(False, "Target is excluded by the configured URL patterns.")
        if target == current:
            return ScopeDecision(True)
        if self.depth + 1 > self.max_depth:
            self._skip(target, "maximum navigation depth reached")
            return ScopeDecision(False, "Maximum navigation depth reached.")
        return ScopeDecision(True)

    def check_action(self, action: PlannedAction, current_url: str) -> ScopeDecision:
        """May this browser action run inside the current scope?"""
        if action.blocked_by_policy:
            return ScopeDecision(False, action.policy_reason or "Blocked by action policy.")

        if self.scope.type == ScopeType.SINGLE_URL:
            if action.type == ActionType.NAVIGATE:
                return ScopeDecision(False, "Single URL scans do not follow links.")
            if action.type == ActionType.SUBMIT_FORM:
                return ScopeDecision(False, "Form submission is disabled for single URL scans.")
            if action.type == ActionType.FILL and self.scope.interaction_depth == InteractionDepth.NONE:
                return ScopeDecision(False, "Interaction testing is disabled for this scan.")
            if action.url and self._normalize(action.url) != self._normalize(self.start_url):
                # Clicking a link would leave the page the user selected.
                return ScopeDecision(
                    False, "Single URL scans stay on the selected URL and do not follow links."
                )
            return ScopeDecision(True)

        if self.scope.type == ScopeType.SELECTED_ELEMENT:
            if action.type in {ActionType.NAVIGATE, ActionType.SUBMIT_FORM}:
                return ScopeDecision(
                    False, "Navigation and form submission are disabled for selected element scans."
                )
            if action.type == ActionType.FILL and self.scope.interaction_depth == InteractionDepth.NONE:
                return ScopeDecision(False, "Interaction testing is disabled for this scan.")
            if action.url and self._normalize(action.url) != self._normalize(self.start_url):
                return ScopeDecision(False, "Selected element scans may not leave the inspected page.")
            if action.selector and self.scope.element_selector:
                if not self._is_within_selected(action.selector):
                    return ScopeDecision(False, "Action targets an element outside the selected region.")
            return ScopeDecision(True)

        # Full site
        if action.type == ActionType.NAVIGATE and action.url:
            return self.check_navigation(current_url, action.url)
        if action.type == ActionType.SUBMIT_FORM and self.scope.interaction_depth == InteractionDepth.NONE:
            return ScopeDecision(False, "Interaction testing is disabled for this scan.")
        return ScopeDecision(True)

    def _is_within_selected(self, selector: str) -> bool:
        root = self.scope.element_selector
        if not root:
            return True
        if selector == root:
            return True
        return selector.startswith(root + " > ") or selector.startswith(root + " ")

    def note_navigation(self, from_url: str, to_url: str) -> None:
        if self._normalize(from_url) != self._normalize(to_url):
            self.depth += 1


def build_scope_guard(scope: ScanScope, current_url: str = "") -> ScopeGuard:
    guard = ScopeGuard(scope=scope)
    if current_url and current_url != scope.start_url:
        guard.depth = 1
    return guard


def scope_summary(scope: ScanScope) -> str:
    """Human readable description of what the scan will and will not touch."""
    if scope.type == ScopeType.SINGLE_URL:
        return f"Single URL: {scope.start_url}"
    if scope.type == ScopeType.SELECTED_ELEMENT:
        target = scope.element_label or scope.element_selector or "selected element"
        return f"Selected element: {target}"
    parts = [f"Full site from {scope.start_url}"]
    if scope.same_origin_only:
        parts.append(f"origin {scope.origin()}")
    if scope.exclude_patterns:
        parts.append("excluding " + ", ".join(scope.exclude_patterns))
    if scope.include_patterns:
        parts.append("including " + ", ".join(scope.include_patterns))
    parts.append(f"max depth {scope.max_depth}")
    return " · ".join(parts)


def resolve_navigation_target(base_url: str, href: str) -> str:
    return urljoin(base_url, href)

from __future__ import annotations

import re

from bugpilot_core.models import ActionType, PlannedAction

DESTRUCTIVE_PATTERNS = [
    r"\bdelete\b",
    r"\bremove\b",
    r"\bpurchase\b",
    r"\bbuy now\b",
    r"\bcheckout\b",
    r"\bpay\b",
    r"\bpayment\b",
    r"\bsend\b",
    r"\bpublish\b",
    r"\btransfer\b",
    r"\bchange password\b",
    r"\bdelete account\b",
    r"\bunsubscribe\b",
    r"\bdrop\b",
    r"\bdestroy\b",
]

DESTRUCTIVE_HREF = [
    r"checkout",
    r"payment",
    r"billing",
    r"/delete",
    r"unsubscribe",
]


class ActionPolicy:
    def __init__(self, *, allow_destructive: bool, environment: str) -> None:
        self.allow_destructive = allow_destructive
        self.environment = environment

    def evaluate(self, action: PlannedAction, element_text: str = "", href: str = "") -> PlannedAction:
        if self.allow_destructive and self.environment != "production":
            action.blocked_by_policy = False
            return action

        haystack = f"{element_text} {href} {action.description} {action.value or ''}".lower()
        for pattern in DESTRUCTIVE_PATTERNS:
            if re.search(pattern, haystack):
                # Checkout as a page to inspect is allowed; submitting payment is not.
                if pattern == r"\bcheckout\b" and action.type in {ActionType.NAVIGATE, ActionType.CLICK}:
                    if not re.search(r"\b(pay|place order|confirm purchase|buy)\b", haystack):
                        continue
                return self._block(action, f"Blocked potentially destructive action matching '{pattern}'.")
        for pattern in DESTRUCTIVE_HREF:
            if href and re.search(pattern, href.lower()):
                if "checkout" in pattern and action.type == ActionType.NAVIGATE:
                    continue
                return self._block(action, f"Blocked navigation to sensitive path '{pattern}'.")
        if action.type == ActionType.SUBMIT_FORM and self.environment == "production":
            return self._block(action, "Form submission is disabled in production by default.")
        return action

    def _block(self, action: PlannedAction, reason: str) -> PlannedAction:
        action.blocked_by_policy = True
        action.policy_reason = reason
        action.risk = max(action.risk, 1.0)
        return action

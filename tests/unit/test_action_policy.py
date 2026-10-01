from bugpilot_core.models import ActionType, PlannedAction
from bugpilot_core.policies.action_policy import ActionPolicy


def test_blocks_purchase_in_production():
    policy = ActionPolicy(allow_destructive=False, environment="production")
    action = PlannedAction(type=ActionType.CLICK, description="Buy now", selector="button.cta")
    result = policy.evaluate(action, "Buy now", "/checkout")
    assert result.blocked_by_policy


def test_allows_navigation_to_checkout_page():
    policy = ActionPolicy(allow_destructive=False, environment="staging")
    action = PlannedAction(type=ActionType.NAVIGATE, description="Open checkout", url="/checkout")
    result = policy.evaluate(action, "Checkout", "/checkout")
    assert result.blocked_by_policy is False


def test_blocks_pay_now():
    policy = ActionPolicy(allow_destructive=False, environment="staging")
    action = PlannedAction(type=ActionType.CLICK, description="Pay now")
    result = policy.evaluate(action, "Pay now", "/pay")
    assert result.blocked_by_policy

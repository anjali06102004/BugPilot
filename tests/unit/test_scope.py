from __future__ import annotations

from bugpilot_core.models import ActionType, InteractionDepth, PlannedAction, ScanScope, ScopeType
from bugpilot_core.scope import ScopeGuard, scope_summary


def guard(scope: ScanScope) -> ScopeGuard:
    return ScopeGuard(scope=scope)


def single_url_scope() -> ScanScope:
    return ScanScope(
        type=ScopeType.SINGLE_URL,
        start_url="https://shop.example.com/cart",
        interaction_depth=InteractionDepth.SAFE,
    )


def test_single_url_never_follows_links():
    scope = single_url_scope()
    action = PlannedAction(
        type=ActionType.CLICK,
        selector="a.checkout",
        url="https://shop.example.com/checkout",
        description="click checkout",
    )
    decision = guard(scope).check_action(action, "https://shop.example.com/cart")
    assert decision.allowed is False
    assert "selected URL" in decision.reason


def test_single_url_allows_safe_click_without_navigation():
    scope = single_url_scope()
    action = PlannedAction(type=ActionType.CLICK, selector="button#pay", description="click pay")
    decision = guard(scope).check_action(action, "https://shop.example.com/cart")
    assert decision.allowed is True


def test_single_url_blocks_navigation_action():
    scope = single_url_scope()
    action = PlannedAction(
        type=ActionType.NAVIGATE, selector="a", url="https://shop.example.com/", description="go"
    )
    assert guard(scope).check_action(action, scope.start_url).allowed is False


def test_single_url_with_interactions_disabled_blocks_fill():
    scope = single_url_scope()
    scope.interaction_depth = InteractionDepth.NONE
    action = PlannedAction(type=ActionType.FILL, selector="input#q", value="x", description="fill")
    assert guard(scope).check_action(action, scope.start_url).allowed is False


def test_selected_element_only_allows_its_subtree():
    scope = ScanScope(
        type=ScopeType.SELECTED_ELEMENT,
        start_url="https://shop.example.com/",
        element_selector="form.checkout",
        interaction_depth=InteractionDepth.SAFE,
    )
    inside = PlannedAction(
        type=ActionType.FILL,
        selector="form.checkout > input#email",
        value="a@b.c",
        description="fill",
    )
    outside = PlannedAction(type=ActionType.CLICK, selector="nav a.home", description="click home")
    g = guard(scope)
    assert g.check_action(inside, scope.start_url).allowed is True
    assert g.check_action(outside, scope.start_url).allowed is False


def test_selected_element_never_navigates():
    scope = ScanScope(
        type=ScopeType.SELECTED_ELEMENT,
        start_url="https://shop.example.com/",
        element_selector="button.cta",
        interaction_depth=InteractionDepth.SAFE,
    )
    action = PlannedAction(
        type=ActionType.CLICK,
        selector="a.cta",
        url="https://shop.example.com/checkout",
        description="click",
    )
    decision = guard(scope).check_action(action, scope.start_url)
    assert decision.allowed is False


def test_full_site_respects_max_depth():
    scope = ScanScope(
        type=ScopeType.FULL_SITE,
        start_url="https://shop.example.com/",
        max_depth=1,
    )
    g = guard(scope)
    assert g.check_navigation(scope.start_url, "https://shop.example.com/a").allowed is True
    g.depth = 1
    assert g.check_navigation("https://shop.example.com/a", "https://shop.example.com/b").allowed is False
    assert any("depth" in reason for _, reason in g.skipped)


def test_full_site_blocks_other_origins():
    scope = ScanScope(type=ScopeType.FULL_SITE, start_url="https://shop.example.com/")
    decision = guard(scope).check_navigation(scope.start_url, "https://evil.example.org/")
    assert decision.allowed is False
    assert "origin" in decision.reason


def test_full_site_patterns_include_and_exclude():
    scope = ScanScope(
        type=ScopeType.FULL_SITE,
        start_url="https://shop.example.com/",
        include_patterns=["https://shop.example.com/products*"],
        exclude_patterns=["*/logout*"],
    )
    g = guard(scope)
    assert g.check_navigation(scope.start_url, "https://shop.example.com/products/1").allowed is True
    assert g.check_navigation(scope.start_url, "https://shop.example.com/account").allowed is False
    assert g.check_navigation(scope.start_url, "https://shop.example.com/products/logout").allowed is False


def test_policy_blocked_action_is_rejected():
    scope = single_url_scope()
    action = PlannedAction(
        type=ActionType.CLICK,
        selector="button.buy",
        description="Buy now",
        blocked_by_policy=True,
        policy_reason="Blocked potentially destructive action",
    )
    decision = guard(scope).check_action(action, scope.start_url)
    assert decision.allowed is False


def test_scope_summary_is_human_readable():
    scope = ScanScope(
        type=ScopeType.FULL_SITE, start_url="https://shop.example.com/", exclude_patterns=["/admin"]
    )
    summary = scope_summary(scope)
    assert "Full site" in summary
    assert "/admin" in summary

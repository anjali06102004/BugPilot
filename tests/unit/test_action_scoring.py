from bugpilot_core.models import ActionType, DomElement, PlannedAction
from bugpilot_core.scoring.actions import score_action


def test_penalizes_already_tested_elements():
    el = DomElement(selector="a.nav", fingerprint="nav1", tag="a", text="Home", interactive=True, visible=True)
    fresh = PlannedAction(type=ActionType.CLICK, selector="a.nav", fingerprint="nav1", description="Home")
    repeat = PlannedAction(type=ActionType.CLICK, selector="a.nav", fingerprint="nav1", description="Home")
    a = score_action(fresh, el, seen_fingerprints=set(), visited_urls=set())
    b = score_action(repeat, el, seen_fingerprints={"nav1"}, visited_urls=set())
    assert a.score > b.score

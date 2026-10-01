from bugpilot_core.detectors.base import PageSnapshot
from bugpilot_core.models import BoundingBox, ConsoleEvent, DomElement, FindingCategory, Viewport
from bugpilot_core.detectors import run_detectors
from bugpilot_core.models import TestCategory


def el(**kwargs) -> DomElement:
    defaults = dict(
        selector="div.x",
        fingerprint="fp",
        tag="div",
        visible=True,
        interactive=False,
        box=BoundingBox(x=0, y=0, width=10, height=10),
        styles={},
        attributes={},
    )
    defaults.update(kwargs)
    return DomElement(**defaults)


def snapshot(**kwargs) -> PageSnapshot:
    defaults = dict(
        url="https://staging.example.com/",
        title="Demo",
        viewport=Viewport(name="mobile-390", width=390, height=844),
        html_lang=None,
        scroll_width=1400,
        client_width=390,
        scroll_height=900,
        client_height=844,
        elements=[],
    )
    defaults.update(kwargs)
    return PageSnapshot(**defaults)


def test_overflow_detector():
    snap = snapshot()
    findings = run_detectors(snap, [TestCategory.VISUAL, TestCategory.RESPONSIVE])
    assert any(f.category == FindingCategory.OVERFLOW for f in findings)


def test_overlap_detector():
    a = el(
        selector="button.cta",
        fingerprint="cta",
        tag="button",
        text="Buy now",
        interactive=True,
        box=BoundingBox(x=250, y=780, width=120, height=48),
    )
    b = el(
        selector="nav a",
        fingerprint="nav",
        tag="a",
        text="Checkout",
        interactive=True,
        box=BoundingBox(x=200, y=780, width=100, height=48),
    )
    snap = snapshot(scroll_width=390, elements=[a, b])
    findings = run_detectors(snap, [TestCategory.VISUAL])
    assert any(f.category == FindingCategory.LAYOUT for f in findings)


def test_broken_image_and_console():
    img = el(
        tag="img",
        selector="img.hero",
        fingerprint="img",
        attributes={"src": "/missing.png", "naturalWidth": "0", "broken": "true"},
    )
    snap = snapshot(
        scroll_width=390,
        elements=[img],
        console=[ConsoleEvent(level="error", text="boom")],
    )
    findings = run_detectors(snap, [TestCategory.CONTENT, TestCategory.CONSOLE, TestCategory.VISUAL])
    cats = {f.category for f in findings}
    assert FindingCategory.BROKEN_IMAGE in cats
    assert FindingCategory.CONSOLE in cats

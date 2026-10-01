"""Playwright integration: run detectors against the broken-shop fixture."""

from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from bugpilot_core.agent.dom_script import DOM_SCRIPT
from bugpilot_core.detectors import run_detectors
from bugpilot_core.detectors.base import PageSnapshot
from bugpilot_core.models import BoundingBox, DomElement, FindingCategory, TestCategory, Viewport


@pytest.mark.asyncio
async def test_broken_shop_file_has_real_bugs():
    html = Path("fixtures/broken-shop/index.html").read_text(encoding="utf-8")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await page.set_content(html, wait_until="domcontentloaded")
        raw = await page.evaluate(DOM_SCRIPT)
        await browser.close()

    elements = [
        DomElement(
            selector=el.get("selector") or "",
            fingerprint=el.get("fingerprint") or "",
            tag=el.get("tag") or "div",
            text=el.get("text") or "",
            visible=bool(el.get("visible")),
            interactive=bool(el.get("interactive")),
            box=BoundingBox(**el["box"]) if el.get("box") else None,
            styles=el.get("styles") or {},
            attributes=el.get("attributes") or {},
        )
        for el in raw["elements"]
    ]
    snap = PageSnapshot(
        url="http://127.0.0.1:4173/",
        title=raw["title"],
        viewport=Viewport(name="mobile-390", width=390, height=844),
        html_lang=raw.get("html_lang"),
        scroll_width=float(raw["scroll_width"]),
        client_width=float(raw["client_width"]),
        scroll_height=float(raw["scroll_height"]),
        client_height=float(raw["client_height"]),
        elements=elements,
    )
    findings = run_detectors(
        snap,
        [TestCategory.VISUAL, TestCategory.RESPONSIVE, TestCategory.ACCESSIBILITY, TestCategory.CONTENT],
    )
    categories = {f.category for f in findings}
    assert FindingCategory.OVERFLOW in categories
    assert FindingCategory.LAYOUT in categories or FindingCategory.BROKEN_IMAGE in categories

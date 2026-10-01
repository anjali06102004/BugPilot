from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4

from playwright.async_api import Browser, Page, async_playwright

from bugpilot_core.agent.dom_script import DOM_SCRIPT
from bugpilot_core.detectors.base import PageSnapshot
from bugpilot_core.models import (
    BoundingBox,
    ConsoleEvent,
    DomElement,
    MascotState,
    NetworkEvent,
    ScanConfig,
    ScanEvent,
    Viewport,
)

EventEmitter = Callable[[ScanEvent], Awaitable[None]]


class BrowserSession:
    def __init__(
        self,
        *,
        session_id: str,
        config: ScanConfig,
        evidence_dir: Path,
        emit: EventEmitter,
    ) -> None:
        self.session_id = session_id
        self.config = config
        self.evidence_dir = evidence_dir / session_id
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.emit = emit
        self._playwright = None
        self.browser: Browser | None = None
        self.page: Page | None = None
        self.console: list[ConsoleEvent] = []
        self.network: list[NetworkEvent] = []
        self.last_action: str | None = None

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        engine = getattr(self._playwright, self.config.browser.value)
        self.browser = await engine.launch(headless=True)
        viewport = self.config.viewports[0]
        context = await self.browser.new_context(
            viewport={"width": viewport.width, "height": viewport.height},
            ignore_https_errors=True,
        )
        self.page = await context.new_page()
        self.page.set_default_timeout(15000)
        self.page.on("console", self._on_console)
        self.page.on("pageerror", self._on_pageerror)
        self.page.on("requestfailed", self._on_request_failed)
        self.page.on("response", self._on_response)

    async def close(self) -> None:
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def goto(self, url: str) -> None:
        assert self.page
        await self.emit(
            ScanEvent(
                type="page.loaded",
                session_id=self.session_id,
                message=f"Opening {url}",
                mascot=MascotState.FLYING,
                payload={"url": url},
            )
        )
        await self.page.goto(url, wait_until="domcontentloaded")
        await self.page.wait_for_timeout(400)

    async def resize(self, viewport: Viewport) -> None:
        assert self.page
        await self.page.set_viewport_size({"width": viewport.width, "height": viewport.height})
        await self.page.wait_for_timeout(250)

    async def snapshot(self, viewport: Viewport) -> PageSnapshot:
        assert self.page
        raw = await self.page.evaluate(DOM_SCRIPT)
        screenshot_path = self.evidence_dir / f"{uuid4().hex}.png"
        await self.page.screenshot(path=str(screenshot_path), full_page=False)
        elements = [
            DomElement(
                selector=el.get("selector") or "",
                fingerprint=hashlib.sha1((el.get("fingerprint") or "").encode()).hexdigest()[:16],
                tag=el.get("tag") or "div",
                role=el.get("role"),
                text=el.get("text") or "",
                href=el.get("href"),
                type=el.get("type"),
                name=el.get("name"),
                id=el.get("id"),
                visible=bool(el.get("visible")),
                interactive=bool(el.get("interactive")),
                disabled=bool(el.get("disabled")),
                box=BoundingBox(**el["box"]) if el.get("box") else None,
                styles=el.get("styles") or {},
                attributes=el.get("attributes") or {},
            )
            for el in raw.get("elements", [])
        ]
        return PageSnapshot(
            url=raw.get("url") or self.page.url,
            title=raw.get("title") or "",
            viewport=viewport,
            html_lang=raw.get("html_lang"),
            scroll_width=float(raw.get("scroll_width") or 0),
            client_width=float(raw.get("client_width") or 0),
            scroll_height=float(raw.get("scroll_height") or 0),
            client_height=float(raw.get("client_height") or 0),
            elements=elements,
            console=list(self.console),
            network=list(self.network),
            screenshot_path=str(screenshot_path),
        )

    async def click(self, selector: str) -> None:
        assert self.page
        self.last_action = f"click {selector}"
        await self.page.locator(selector).first.click(timeout=8000)

    async def fill(self, selector: str, value: str) -> None:
        assert self.page
        self.last_action = f"fill {selector}"
        await self.page.locator(selector).first.fill(value, timeout=8000)

    async def hover(self, selector: str) -> None:
        assert self.page
        self.last_action = f"hover {selector}"
        await self.page.locator(selector).first.hover(timeout=8000)

    async def scroll(self) -> None:
        assert self.page
        self.last_action = "scroll"
        await self.page.mouse.wheel(0, 600)

    def _on_console(self, msg: Any) -> None:
        if msg.type in {"error", "warning"}:
            self.console.append(
                ConsoleEvent(level="error" if msg.type == "error" else "warn", text=msg.text, url=self.page.url if self.page else None)
            )

    def _on_pageerror(self, error: Any) -> None:
        self.console.append(ConsoleEvent(level="pageerror", text=str(error), url=self.page.url if self.page else None))

    def _on_request_failed(self, request: Any) -> None:
        failure = request.failure()
        self.network.append(
            NetworkEvent(
                method=request.method,
                url=request.url,
                failed=True,
                failure_text=failure,
                resource_type=request.resource_type,
                associated_action=self.last_action,
            )
        )

    def _on_response(self, response: Any) -> None:
        status = response.status
        if status >= 400:
            self.network.append(
                NetworkEvent(
                    method=response.request.method,
                    url=response.url,
                    status=status,
                    failed=True,
                    resource_type=response.request.resource_type,
                    associated_action=self.last_action,
                )
            )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)

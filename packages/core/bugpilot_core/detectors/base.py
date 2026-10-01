from __future__ import annotations

from dataclasses import dataclass, field

from bugpilot_core.models import (
    BoundingBox,
    ConsoleEvent,
    DomElement,
    FindingCandidate,
    NetworkEvent,
    Viewport,
)


@dataclass
class PageSnapshot:
    url: str
    title: str
    viewport: Viewport
    html_lang: str | None
    scroll_width: float
    client_width: float
    scroll_height: float
    client_height: float
    elements: list[DomElement]
    console: list[ConsoleEvent] = field(default_factory=list)
    network: list[NetworkEvent] = field(default_factory=list)
    screenshot_path: str | None = None


def boxes_intersect(a: BoundingBox, b: BoundingBox, min_area: float = 24.0) -> float:
    x1 = max(a.x, b.x)
    y1 = max(a.y, b.y)
    x2 = min(a.x + a.width, b.x + b.width)
    y2 = min(a.y + a.height, b.y + b.height)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    return (x2 - x1) * (y2 - y1) if (x2 - x1) * (y2 - y1) >= min_area else 0.0


def parent_child(a: DomElement, b: DomElement) -> bool:
    if not a.selector or not b.selector:
        return False
    return a.selector.startswith(b.selector) or b.selector.startswith(a.selector)


def candidate(
    snapshot: PageSnapshot,
    *,
    category,
    title: str,
    description: str,
    source: str,
    confidence: float,
    selector: str | None = None,
    fingerprint: str | None = None,
    expected: str | None = None,
    actual: str | None = None,
    error_signature: str | None = None,
    metadata: dict | None = None,
) -> FindingCandidate:
    from bugpilot_core.models import EvidenceItem

    evidence = [
        EvidenceItem(kind="url", content={"url": snapshot.url}),
        EvidenceItem(
            kind="viewport",
            content={"name": snapshot.viewport.name, "width": snapshot.viewport.width, "height": snapshot.viewport.height},
        ),
    ]
    if snapshot.screenshot_path:
        evidence.append(EvidenceItem(kind="screenshot", path=snapshot.screenshot_path))
    return FindingCandidate(
        category=category,
        title=title,
        description=description,
        confidence=confidence,
        source=source,
        selector=selector,
        fingerprint=fingerprint,
        url=snapshot.url,
        viewport=snapshot.viewport,
        evidence=evidence,
        expected=expected,
        actual=actual,
        error_signature=error_signature,
        metadata=metadata or {},
    )

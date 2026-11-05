"""Content and readability checks.

Covers defects that are neither layout nor accessibility: text that is cut
off, content that cannot be read at the tested viewport, and large blank
regions that usually mean a component failed to render.
"""

from __future__ import annotations

from bugpilot_core.detectors.base import PageSnapshot, candidate
from bugpilot_core.models import FindingCandidate, FindingCategory

TEXT_TAGS = {"p", "span", "li", "h1", "h2", "h3", "h4", "h5", "h6", "a", "label", "td", "th"}


def _style(el, key: str) -> str:
    return str((el.styles or {}).get(key, "") or "").strip().lower()


def detect_content(snapshot: PageSnapshot) -> list[FindingCandidate]:
    findings: list[FindingCandidate] = []

    for el in snapshot.elements:
        if el.tag not in TEXT_TAGS or not el.visible or not el.text.strip():
            continue
        overflow = _style(el, "textOverflow") or _style(el, "text-overflow")
        text_overflow = _style(el, "overflow")
        if overflow == "clip" and text_overflow == "hidden":
            findings.append(
                candidate(
                    snapshot,
                    category=FindingCategory.CONTENT,
                    title=f"Text is cut off: {el.tag}",
                    description=(
                        f"{el.selector} clips its text (text-overflow: clip) so the copy is unreadable."
                    ),
                    source="content_detector",
                    confidence=0.78,
                    selector=el.selector,
                    fingerprint=el.fingerprint,
                    expected="Long copy wraps or is truncated with an ellipsis.",
                    actual="Text is clipped with no visible overflow indicator.",
                    error_signature=f"content:clip:{el.fingerprint}",
                    metadata={"user_impact": 0.45, "readability_impact": 0.6},
                )
            )
        font_size = _style(el, "fontSize")
        if font_size.endswith("px"):
            try:
                size = float(font_size[:-2])
            except ValueError:
                size = 0.0
            if 0 < size < 10 and len(el.text) > 40:
                findings.append(
                    candidate(
                        snapshot,
                        category=FindingCategory.CONTENT,
                        title=f"Text is too small to read: {el.tag}",
                        description=f"{el.selector} renders at {font_size}, below the 10px legibility floor.",
                        source="content_detector",
                        confidence=0.7,
                        selector=el.selector,
                        fingerprint=el.fingerprint,
                        expected="Body copy is rendered at a legible size (>= 10px).",
                        actual=f"font-size: {font_size}",
                        error_signature=f"content:tiny-text:{el.fingerprint}",
                        metadata={"user_impact": 0.4, "accessibility_impact": 0.5},
                    )
                )

    # A very tall viewport with almost nothing rendered usually means a
    # component failed to mount rather than that the page is genuinely empty.
    if snapshot.client_height > 200 and snapshot.scroll_height > snapshot.client_height * 2.5:
        findings.append(
            candidate(
                snapshot,
                category=FindingCategory.CONTENT,
                title="Large blank region in page",
                description=(
                    f"The document is {snapshot.scroll_height:.0f}px tall but only "
                    f"{snapshot.client_height:.0f}px of it was visible at first render."
                ),
                source="content_detector",
                confidence=0.6,
                expected="The page fills its content area with rendered UI.",
                actual="A large part of the document height produced no visible content.",
                error_signature=f"content:blank-region:{snapshot.viewport.name}",
                metadata={"user_impact": 0.5, "workflow_impact": 0.4},
            )
        )
    return findings

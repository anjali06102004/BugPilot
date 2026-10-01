from __future__ import annotations

from typing import Any

from bugpilot_core.ai.providers.base import (
    ProviderCapabilities,
    ReasoningResult,
    VisionAnalysis,
)


class LocalProvider:
    """Deterministic fallback when no API key is configured. Never invents bugs."""

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(name="local", multimodal=False, structured_output=True)

    async def analyze_vision(self, *, prompt: str, image_bytes: bytes, context: dict[str, Any]) -> VisionAnalysis:
        return VisionAnalysis(anomalies=[], notes="LocalProvider skipped vision (no cloud model).", should_verify=False)

    async def reason(self, *, prompt: str, context: dict[str, Any]) -> ReasoningResult:
        candidate = context.get("candidate") or {}
        return ReasoningResult(
            label="likely" if candidate else "possible",
            what_should_happen=str(candidate.get("expected") or "UI remains usable."),
            what_happened=str(candidate.get("actual") or "Detector flagged an anomaly."),
            is_expected=False,
            evidence_summary="Deterministic detector evidence only; no LLM reasoning available.",
            should_verify=True,
            reproduction_steps=list(candidate.get("steps") or []),
            root_cause=None,
            suggested_fix=None,
        )

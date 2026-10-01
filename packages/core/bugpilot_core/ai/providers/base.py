from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field


class VisionAnomaly(BaseModel):
    title: str
    description: str
    severity_guess: str = "medium"
    confidence: float = Field(ge=0, le=1)
    selector_hint: str | None = None
    expected: str | None = None
    actual: str | None = None


class VisionAnalysis(BaseModel):
    anomalies: list[VisionAnomaly] = Field(default_factory=list)
    notes: str = ""
    should_verify: bool = False


class ReasoningResult(BaseModel):
    label: str
    what_should_happen: str
    what_happened: str
    is_expected: bool
    evidence_summary: str
    should_verify: bool
    reproduction_steps: list[str] = Field(default_factory=list)
    root_cause: str | None = None
    suggested_fix: str | None = None


class ProviderCapabilities(BaseModel):
    name: str
    multimodal: bool
    structured_output: bool


class AIProvider(Protocol):
    def capabilities(self) -> ProviderCapabilities: ...

    async def analyze_vision(self, *, prompt: str, image_bytes: bytes, context: dict[str, Any]) -> VisionAnalysis: ...

    async def reason(self, *, prompt: str, context: dict[str, Any]) -> ReasoningResult: ...

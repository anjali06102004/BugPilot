from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from bugpilot_core.ai.providers.base import (
    ProviderCapabilities,
    ReasoningResult,
    VisionAnalysis,
)
from bugpilot_core.ai.providers.local import LocalProvider


class GeminiProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model
        self._fallback = LocalProvider()

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(name="gemini", multimodal=True, structured_output=True)

    async def analyze_vision(self, *, prompt: str, image_bytes: bytes, context: dict[str, Any]) -> VisionAnalysis:
        if not self.api_key:
            return await self._fallback.analyze_vision(prompt=prompt, image_bytes=image_bytes, context=context)
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            return await self._fallback.analyze_vision(prompt=prompt, image_bytes=image_bytes, context=context)

        client = genai.Client(api_key=self.api_key)
        schema_hint = VisionAnalysis.model_json_schema()
        contents = [
            types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
            prompt
            + "\nRespond with JSON matching this schema:\n"
            + json.dumps(schema_hint)
            + "\nContext:\n"
            + json.dumps(context, default=str)[:8000],
        ]
        response = await _generate(client, self.model, contents)
        return _parse(VisionAnalysis, response, VisionAnalysis())

    async def reason(self, *, prompt: str, context: dict[str, Any]) -> ReasoningResult:
        if not self.api_key:
            return await self._fallback.reason(prompt=prompt, context=context)
        try:
            from google import genai
        except ImportError:
            return await self._fallback.reason(prompt=prompt, context=context)
        client = genai.Client(api_key=self.api_key)
        schema_hint = ReasoningResult.model_json_schema()
        text = (
            prompt
            + "\nRespond with JSON matching this schema:\n"
            + json.dumps(schema_hint)
            + "\nContext:\n"
            + json.dumps(context, default=str)[:8000]
        )
        response = await _generate(client, self.model, [text])
        fallback = await self._fallback.reason(prompt=prompt, context=context)
        return _parse(ReasoningResult, response, fallback)


async def _generate(client: Any, model: str, contents: list[Any]) -> str:
    try:
        result = client.models.generate_content(
            model=model,
            contents=contents,
            config={"response_mime_type": "application/json", "temperature": 0.1},
        )
        return getattr(result, "text", None) or "{}"
    except Exception:
        return "{}"


def _parse(model_cls, text: str, fallback):
    try:
        return model_cls.model_validate_json(text)
    except (ValidationError, ValueError):
        try:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                return model_cls.model_validate_json(text[start : end + 1])
        except (ValidationError, ValueError):
            return fallback
        return fallback

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


class OpenAIProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model
        self._fallback = LocalProvider()

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(name="openai", multimodal=True, structured_output=True)

    async def analyze_vision(self, *, prompt: str, image_bytes: bytes, context: dict[str, Any]) -> VisionAnalysis:
        if not self.api_key:
            return await self._fallback.analyze_vision(prompt=prompt, image_bytes=image_bytes, context=context)
        try:
            from openai import AsyncOpenAI
        except ImportError:
            return await self._fallback.analyze_vision(prompt=prompt, image_bytes=image_bytes, context=context)

        import base64

        client = AsyncOpenAI(api_key=self.api_key)
        b64 = base64.b64encode(image_bytes).decode("ascii")
        response = await client.chat.completions.create(
            model=self.model,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt + "\n" + json.dumps(context, default=str)[:8000]},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                }
            ],
        )
        text = response.choices[0].message.content or "{}"
        return _parse(VisionAnalysis, text, VisionAnalysis())

    async def reason(self, *, prompt: str, context: dict[str, Any]) -> ReasoningResult:
        if not self.api_key:
            return await self._fallback.reason(prompt=prompt, context=context)
        try:
            from openai import AsyncOpenAI
        except ImportError:
            return await self._fallback.reason(prompt=prompt, context=context)
        client = AsyncOpenAI(api_key=self.api_key)
        response = await client.chat.completions.create(
            model=self.model,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "user",
                    "content": prompt + "\n" + json.dumps(context, default=str)[:8000],
                }
            ],
        )
        text = response.choices[0].message.content or "{}"
        fallback = await self._fallback.reason(prompt=prompt, context=context)
        return _parse(ReasoningResult, text, fallback)


def _parse(model_cls, text: str, fallback):
    try:
        return model_cls.model_validate_json(text)
    except (ValidationError, ValueError):
        return fallback

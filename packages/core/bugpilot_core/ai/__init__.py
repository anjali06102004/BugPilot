from bugpilot_core.ai.providers.base import AIProvider
from bugpilot_core.ai.providers.gemini import GeminiProvider
from bugpilot_core.ai.providers.local import LocalProvider
from bugpilot_core.ai.providers.openai import OpenAIProvider
from bugpilot_core.config import Settings


def build_provider(settings: Settings) -> AIProvider:
    name = (settings.ai_provider or "local").lower()
    if name == "gemini" and settings.gemini_api_key:
        return GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    if name == "openai" and settings.openai_api_key:
        return OpenAIProvider(settings.openai_api_key, settings.openai_model)
    if name == "gemini":
        return GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    if name == "openai":
        return OpenAIProvider(settings.openai_api_key, settings.openai_model)
    return LocalProvider()

"""Pre-turn task complexity classifier.

Runs a single cheap LLM call before each user turn to classify the task
as simple / medium / complex, then returns the model name configured for
that tier. Disabled by default — enable via config.classifier.enabled.
"""

from __future__ import annotations

from loguru import logger

from mybot.config.schema import ClassifierConfig
from mybot.providers.base import LLMProvider
from mybot.templates import load as _load

_SYSTEM = _load("classifier", "system")


class PreTurnClassifier:
    """Classifies each incoming message and returns the appropriate model name."""

    def __init__(self, provider: LLMProvider, config: ClassifierConfig) -> None:
        self._provider = provider
        self._config = config
        self._tier_models = {
            "simple": config.simple_model,
            "medium": config.medium_model,
            "complex": config.complex_model,
        }

    async def select_model(self, message: str, history: list[dict]) -> str:
        """Classify *message* and return the model name to use for this turn."""
        tier = await self._classify(message, history)
        model = self._tier_models[tier]
        logger.debug("Classifier: '{}...' → {} → {}", message[:60], tier, model)
        return model

    async def _classify(self, message: str, history: list[dict]) -> str:
        messages = self._build_messages(message, history)
        try:
            response = await self._provider.chat_with_retry(
                messages=messages,
                model=self._config.classifier_model,
                max_tokens=5,
                temperature=0.0,
            )
            return self._parse(response.content)
        except Exception as exc:
            logger.warning("Classifier error: {} — falling back to complex model", exc)
            return "complex"

    def _build_messages(self, message: str, history: list[dict]) -> list[dict]:
        msgs: list[dict] = [{"role": "system", "content": _SYSTEM}]
        # Include the last two turns so the classifier has conversational context
        # without an expensive full-history prompt.
        for m in history[-4:]:
            role = m.get("role")
            content = m.get("content")
            if role in ("user", "assistant") and isinstance(content, str):
                msgs.append({"role": role, "content": content[:400]})
        msgs.append({"role": "user", "content": message[:1000]})
        return msgs

    @staticmethod
    def _parse(raw: str | None) -> str:
        text = (raw or "").strip().lower()
        if "simple" in text:
            return "simple"
        if "complex" in text:
            return "complex"
        if "medium" in text:
            return "medium"
        logger.warning("Classifier returned unrecognised output {!r} — using complex", raw)
        return "complex"

"""Language-model providers.

The engine never depends on a model. A provider only *phrases* answers that the
engine already grounded in catalog facts. Two providers ship:

* SimulatedProvider (default) - deterministic, offline, free. It returns the
  grounded draft verbatim, so demos and tests run without credentials.
* AnthropicProvider (optional) - rewrites the draft conversationally using the
  Claude API. Requires ANTHROPIC_API_KEY and DECISION_GUIDE_LLM_MODEL. Only the
  draft and the grounding facts are sent; nothing else.

Both expose the same `rephrase(draft, facts)` method, and the chat layer
validates the result against the facts regardless of provider.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


class ProviderError(RuntimeError):
    """Raised when a provider cannot be constructed or fails at call time."""


class Provider(Protocol):
    name: str

    def rephrase(self, draft: str, facts: list[str]) -> str: ...


@dataclass
class SimulatedProvider:
    """Offline stand-in. Marked clearly so nobody mistakes it for a model."""

    name: str = "simulated"

    def rephrase(self, draft: str, facts: list[str]) -> str:  # noqa: ARG002
        return draft


SYSTEM_PROMPT = (
    "You rewrite a draft answer about home-office equipment so it reads naturally. "
    "Use ONLY the facts provided. Do not add products, prices, specs, or opinions "
    "that are not in the facts. Keep product ids (like chr-02) exactly as given. "
    "If the draft says something cannot be answered, keep that meaning. "
    "Reply with the rewritten answer only."
)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None, client=None):
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model or os.environ.get("DECISION_GUIDE_LLM_MODEL")
        if client is not None:
            self._client = client
        else:
            if not api_key:
                raise ProviderError("ANTHROPIC_API_KEY is not set")
            if not self.model:
                raise ProviderError("DECISION_GUIDE_LLM_MODEL is not set (pick a model id from the Claude docs)")
            try:
                import anthropic  # type: ignore
            except ImportError as exc:  # pragma: no cover - depends on optional extra
                raise ProviderError("install the optional extra: pip install -e '.[llm]'") from exc
            self._client = anthropic.Anthropic(api_key=api_key)

    def rephrase(self, draft: str, facts: list[str]) -> str:
        content = "FACTS:\n- " + "\n- ".join(facts) + f"\n\nDRAFT:\n{draft}"
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=400,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
            )
        except Exception as exc:  # network, auth, rate limit - all surfaced, never swallowed
            raise ProviderError(f"model call failed: {exc}") from exc
        text = "".join(getattr(block, "text", "") for block in response.content).strip()
        if not text:
            raise ProviderError("model returned an empty response")
        return text


def provider_from_env() -> Provider:
    kind = os.environ.get("DECISION_GUIDE_LLM_PROVIDER", "simulated").lower()
    if kind == "simulated":
        return SimulatedProvider()
    if kind == "anthropic":
        return AnthropicProvider()
    raise ProviderError(f"unknown provider {kind!r} (use 'simulated' or 'anthropic')")

"""Provider neutral interface for text completion."""

from __future__ import annotations

from typing import Protocol


class LLMError(RuntimeError):
    """Raised when a provider call fails or returns something unusable."""


class LLMClient(Protocol):
    name: str
    model: str

    def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 1500) -> str:
        """Return the model's text reply to a single user prompt."""
        ...

"""Anthropic and OpenAI chat clients built on httpx. No vendor SDKs needed."""

from __future__ import annotations

import os
from collections.abc import Mapping

import httpx

from .base import LLMClient, LLMError

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4o-mini",
}


class AnthropicClient:
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        *,
        client: httpx.Client | None = None,
        base_url: str = "https://api.anthropic.com",
    ):
        self.api_key = api_key
        self.model = model or DEFAULT_MODELS["anthropic"]
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=90)

    def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 1500) -> str:
        body: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
        try:
            response = self._client.post(
                f"{self.base_url}/v1/messages",
                json=body,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMError(f"Anthropic request failed: {exc}") from exc
        parts = [block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"]
        if not parts:
            raise LLMError("Anthropic response had no text content")
        return "".join(parts)


class OpenAIClient:
    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        *,
        client: httpx.Client | None = None,
        base_url: str = "https://api.openai.com",
    ):
        self.api_key = api_key
        self.model = model or DEFAULT_MODELS["openai"]
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=90)

    def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 1500) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            response = self._client.post(
                f"{self.base_url}/v1/chat/completions",
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": 0,
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"OpenAI request failed: {exc}") from exc


def llm_from_env(preferred: str | None = None, env: Mapping[str, str] | None = None) -> LLMClient | None:
    """Pick a provider from RESEARCH_LLM or whichever API key is set. Returns None if none is."""
    env = os.environ if env is None else env
    choice = (preferred or env.get("RESEARCH_LLM", "")).strip().lower()
    if choice == "none":
        return None
    model = env.get("RESEARCH_LLM_MODEL") or None
    keys = {"anthropic": env.get("ANTHROPIC_API_KEY"), "openai": env.get("OPENAI_API_KEY")}
    if choice:
        if choice not in keys:
            raise ValueError(f"unknown LLM provider {choice!r}; use anthropic, openai or none")
        if not keys[choice]:
            raise ValueError(f"RESEARCH_LLM={choice} but its API key is not set")
        order = [choice]
    else:
        order = ["anthropic", "openai"]
    for name in order:
        key = keys[name]
        if key:
            return AnthropicClient(key, model) if name == "anthropic" else OpenAIClient(key, model)
    return None

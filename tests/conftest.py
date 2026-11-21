from __future__ import annotations

import pytest

from research_agent.models import Credibility, Document, Plan, Report, Section, Source, SubQuery


def make_source(sid: int, paragraphs: list[str], url: str | None = None, title: str | None = None) -> Source:
    doc = Document(
        url=url or f"https://site{sid}.example.org/page",
        title=title or f"Source {sid}",
        paragraphs=paragraphs,
    )
    return Source(sid, doc, Credibility(0.8, "high", ("+0.10 test",)))


def make_report(sections: list[Section], sources: list[Source]) -> Report:
    plan = Plan("Test question?", "what", "test", (SubQuery("Overview", "test"),))
    return Report("Test question?", sections, {s.id: s for s in sources}, plan, mode="test")


class FakeLLM:
    """Returns canned replies in order and records every prompt."""

    name = "fake"
    model = "fake-1"

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 1500) -> str:
        self.prompts.append(prompt)
        if not self.replies:
            raise AssertionError("FakeLLM ran out of replies")
        return self.replies.pop(0)


@pytest.fixture
def fake_llm():
    return FakeLLM

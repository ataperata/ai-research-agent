"""Plain data types passed between pipeline stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlsplit


def domain_of(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host[4:] if host.startswith("www.") else host


@dataclass(frozen=True)
class SubQuery:
    facet: str
    query: str


@dataclass(frozen=True)
class Plan:
    question: str
    question_type: str
    topic: str
    subqueries: tuple[SubQuery, ...]


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str
    provider: str
    rank: int = 0


@dataclass
class Document:
    url: str
    title: str
    paragraphs: list[str]
    author: str | None = None
    published: str | None = None
    final_url: str | None = None
    outbound_links: int = 0
    has_references: bool = False

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs)

    @property
    def domain(self) -> str:
        return domain_of(self.final_url or self.url)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Document:
        return cls(**data)


@dataclass(frozen=True)
class Credibility:
    score: float
    label: str
    reasons: tuple[str, ...]


@dataclass
class Source:
    id: int
    document: Document
    credibility: Credibility
    found_by: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return self.document.final_url or self.document.url

    @property
    def title(self) -> str:
        return self.document.title or self.document.domain


@dataclass(frozen=True)
class Claim:
    text: str
    source_id: int
    facet: str
    score: float
    position: int
    signal: float = 0.0


@dataclass
class ReportSentence:
    text: str
    sources: list[int]
    # Filled in by the verifier.
    status: str = "unchecked"
    support: float = 0.0
    evidence: dict[int, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return self.status not in ("supported", "unchecked")


@dataclass
class Section:
    title: str
    sentences: list[ReportSentence]
    bullets: bool = False


@dataclass
class Exclusion:
    url: str
    reason: str


@dataclass
class Report:
    question: str
    sections: list[Section]
    sources: dict[int, Source]
    plan: Plan
    exclusions: list[Exclusion] = field(default_factory=list)
    mode: str = "live"
    generated: str = ""

    def all_sentences(self) -> list[ReportSentence]:
        return [s for section in self.sections for s in section.sentences]

"""Write the report body from ranked claims.

Two strategies share one output format (a list of Sections of cited sentences):

* extractive: picks the strongest, least redundant claims and quotes them with their
  sources. Deterministic and needs no model, which is what the offline demo uses.
* llm: hands the ranked claims to a model and asks for a JSON report that cites source
  ids. Whatever comes back still goes through the verifier.
"""

from __future__ import annotations

import json
import re

from .llm.base import LLMClient, LLMError
from .models import Claim, Plan, ReportSentence, Section, Source
from .text import containment, content_terms, jaccard

DUPLICATE_THRESHOLD = 0.5


def _weight(claim: Claim, sources: dict[int, Source]) -> float:
    return claim.score * (0.5 + sources[claim.source_id].credibility.score)


def _finish(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?", '."', ".'")) else text + "."


def synthesize_extractive(
    plan: Plan,
    claims: list[Claim],
    sources: dict[int, Source],
    *,
    summary_size: int = 4,
    per_section: int = 4,
) -> list[Section]:
    usable = [c for c in claims if c.source_id in sources]
    ranked = sorted(usable, key=lambda c: (-_weight(c, sources), c.source_id, c.position))
    terms = {id(c): content_terms(c.text) for c in ranked}
    used_terms: list[list[str]] = []

    def redundant(claim: Claim) -> bool:
        mine = terms[id(claim)]
        return any(
            jaccard(mine, seen) >= DUPLICATE_THRESHOLD or containment(mine, seen) >= 0.8
            for seen in used_terms
        )

    def corroborating(claim: Claim) -> list[int]:
        ids = [claim.source_id]
        for other in ranked:
            if other.source_id not in ids and jaccard(terms[id(claim)], terms[id(other)]) >= 0.55:
                ids.append(other.source_id)
        return ids

    def take(claim: Claim) -> ReportSentence:
        used_terms.append(terms[id(claim)])
        return ReportSentence(_finish(claim.text), corroborating(claim))

    # Key findings: best claims overall, at most one per source so no single page dominates.
    # Claims that carry evidence (a measured number, "found", "estimated") are tried first.
    evidence_first = sorted(
        ranked, key=lambda c: (c.signal < 0.2, -_weight(c, sources), c.source_id, c.position)
    )
    summary: list[ReportSentence] = []
    summary_sources: set[int] = set()
    for claim in evidence_first:
        if len(summary) >= summary_size:
            break
        if claim.source_id in summary_sources or redundant(claim):
            continue
        summary_sources.add(claim.source_id)
        summary.append(take(claim))

    sections = [Section("Key findings", summary, bullets=True)] if summary else []
    for subquery in plan.subqueries:
        picked: list[ReportSentence] = []
        for claim in ranked:
            if len(picked) >= per_section:
                break
            if claim.facet == subquery.facet and not redundant(claim):
                picked.append(take(claim))
        if picked:
            sections.append(Section(subquery.facet, picked))
    return sections


SYNTH_SYSTEM = (
    "You write short, neutral research reports. Every sentence that states a fact must cite "
    "one or more source ids from the evidence list, and must be directly supported by that "
    "source's text. Do not add facts that are not in the evidence."
)

SYNTH_PROMPT = """Question: {question}

Evidence (each line: [source id] (credibility) claim):
{evidence}

Write the report as JSON only, in this shape:
{{"sections": [{{"title": "Key findings", "bullets": true,
  "sentences": [{{"text": "One sentence.", "sources": [1, 3]}}]}},
  {{"title": "Section title", "bullets": false, "sentences": [...]}}]}}
Use the first section for 3 to 5 key findings, then 2 to 4 themed sections. Prefer
higher credibility sources and say so plainly when sources disagree."""


def synthesize_llm(
    plan: Plan,
    claims: list[Claim],
    sources: dict[int, Source],
    llm: LLMClient,
    *,
    max_claims: int = 40,
) -> list[Section]:
    ranked = sorted(
        (c for c in claims if c.source_id in sources),
        key=lambda c: (-_weight(c, sources), c.source_id, c.position),
    )[:max_claims]
    evidence = "\n".join(
        f"[{c.source_id}] ({sources[c.source_id].credibility.label}) {c.text}" for c in ranked
    )
    raw = llm.complete(
        SYNTH_PROMPT.format(question=plan.question, evidence=evidence), system=SYNTH_SYSTEM, max_tokens=2500
    )
    return parse_llm_sections(raw, set(sources))


def parse_llm_sections(raw: str, valid_ids: set[int]) -> list[Section]:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise LLMError("synthesizer returned no JSON")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise LLMError(f"synthesizer returned invalid JSON: {exc}") from exc
    sections: list[Section] = []
    for item in data.get("sections", []):
        sentences = []
        for row in item.get("sentences", []):
            text = str(row.get("text", "")).strip()
            if not text:
                continue
            ids = []
            for value in row.get("sources", []):
                try:
                    sid = int(value)
                except (TypeError, ValueError):
                    continue
                if sid in valid_ids and sid not in ids:
                    ids.append(sid)
            sentences.append(ReportSentence(_finish(text), ids))
        if sentences:
            sections.append(Section(str(item.get("title", "Findings")), sentences, bool(item.get("bullets"))))
    if not sections:
        raise LLMError("synthesizer returned no sections")
    return sections

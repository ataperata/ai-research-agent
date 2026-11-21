"""Pull candidate factual claims out of source text and rank them against the plan."""

from __future__ import annotations

import re

from .models import Claim, Plan, Source
from .text import BM25, content_terms, numbers_in, split_sentences

REPORTING = re.compile(
    r"\b(found|finds|estimated|estimates|reported|reports|measured|showed|shows|concluded|"
    r"according to|analy[sz]ed|requires|recorded|observed)\b",
    re.I,
)
OPINION = re.compile(
    r"\b(i think|i believe|in my opinion|imo|we think|obviously|clearly|everybody knows|"
    r"everyone knows|honestly|amazing|awesome|terrible|useless|click here|subscribe)\b|!",
    re.I,
)
# Sentences that lean on the one before them ("They found...") make no sense on their own.
ANAPHORA = re.compile(
    r"^(they|it|this|these|that|those|he|she|its|their|such|here|however|also|but|instead|"
    r"meanwhile|as a result|in contrast|the resulting|the same|"
    r"the (report|study|authors|researchers|paper|survey|review|analysis|increase|decrease|"
    r"change|effect|result|difference|figure))\b|^(many|some|most|both|few|several) "
    r"(are|were|have|had|of|can|will|do)\b",
    re.I,
)
MEASURE = re.compile(r"percent|%|\$|°|kilowatt|\bkwh\b|million|billion", re.I)
YEAR = re.compile(r"^(1[5-9]|20)\d{2}$")
SELF_REFERENCE = re.compile(r"^(this (page|article|post|site)|read more|share this|see also)", re.I)


def _is_candidate(sentence: str) -> bool:
    words = sentence.split()
    if not 7 <= len(words) <= 60:
        return False
    if sentence.endswith("?") or SELF_REFERENCE.search(sentence):
        return False
    return sentence[0].isupper() or sentence[0].isdigit() or sentence[0] in "\"'("


def extract_claims(plan: Plan, sources: list[Source], per_source_limit: int = 12) -> list[Claim]:
    """Score every sentence for relevance and factual signal, keep the best few per source."""
    rows: list[tuple[int, int, str, bool]] = []
    for source in sources:
        position = 0
        for paragraph in source.document.paragraphs:
            previous = ""
            for sentence in split_sentences(paragraph):
                dangling = bool(ANAPHORA.search(sentence))
                text = sentence
                # Pull in the previous sentence for context when it keeps the claim short.
                if dangling and previous and len(previous.split()) + len(sentence.split()) <= 55:
                    text, dangling = f"{previous} {sentence}", False
                if _is_candidate(sentence):
                    rows.append((source.id, position, text, dangling))
                previous = sentence
                position += 1
    if not rows:
        return []

    tokens = [content_terms(text) for _, _, text, _ in rows]
    index = BM25(tokens)
    question_terms = content_terms(plan.question) + content_terms(plan.topic)
    facet_terms = [(sq.facet, content_terms(sq.query)) for sq in plan.subqueries]

    question_scores = [index.score(question_terms, i) for i in range(len(rows))]
    facet_scores = [[index.score(terms, i) for _, terms in facet_terms] for i in range(len(rows))]
    sentence_raw = [
        max(q, 0.8 * max(f, default=0.0)) for q, f in zip(question_scores, facet_scores, strict=True)
    ]
    top = max(sentence_raw) or 1.0

    # Document level relevance: a sentence in a page that is squarely on topic gets some credit
    # even if it does not repeat the question's words ("To qualify, a system must...").
    doc_index = BM25([content_terms(s.document.text) for s in sources])
    doc_raw = {s.id: doc_index.score(question_terms, n) for n, s in enumerate(sources)}
    doc_top = max(doc_raw.values()) or 1.0

    claims: list[Claim] = []
    for i, (source_id, position, text, dangling) in enumerate(rows):
        relevance = 0.75 * sentence_raw[i] / top + 0.25 * doc_raw[source_id] / doc_top
        if sentence_raw[i] == 0 or relevance < 0.2:
            continue
        signal = 0.0
        numbers = numbers_in(text)
        if any(not YEAR.match(n) for n in numbers):
            signal += 0.15  # a measured quantity, not just a date
        elif numbers:
            signal += 0.05
        if MEASURE.search(text):
            signal += 0.10
        if REPORTING.search(text):
            signal += 0.15
        if dangling:
            continue  # leans on a sentence we could not attach, so it would mislead on its own
        if re.search(r"\s[A-Z][a-z]+", text[1:]):
            signal += 0.05
        if OPINION.search(text):
            signal -= 0.35
        # Mild preference for sentences early in a document, where summaries usually sit.
        signal += max(0.0, 0.05 - 0.005 * position)
        best, facet = 0.0, plan.subqueries[0].facet
        for score, (name, _) in zip(facet_scores[i], facet_terms, strict=True):
            if score > best + 1e-9:
                best, facet = score, name
        claims.append(Claim(text, source_id, facet, round(relevance + signal, 4), position, round(signal, 4)))

    kept: list[Claim] = []
    by_source: dict[int, list[Claim]] = {}
    for claim in claims:
        by_source.setdefault(claim.source_id, []).append(claim)
    for source_id in sorted(by_source):
        ranked = sorted(by_source[source_id], key=lambda c: (-c.score, c.position))
        kept.extend(ranked[:per_source_limit])
    return sorted(kept, key=lambda c: (-c.score, c.source_id, c.position))

"""Check every report sentence against the sources it cites.

Offline the check is a heuristic: content-word recall of the sentence inside the best
matching window of the cited source, blended with character trigram similarity, plus a
hard rule that every number in the sentence must appear in that window. With an LLM
configured, sentences the heuristic finds borderline get a second opinion from the model.
"""

from __future__ import annotations

import itertools
import math
import re
from collections import Counter
from functools import lru_cache
from typing import NamedTuple

from .llm.base import LLMClient, LLMError
from .models import Report, ReportSentence, Source
from .text import char_ngrams, content_terms, cosine, numbers_in, split_sentences, strip_citations

SUPPORTED = 0.55
WEAK = 0.35


class _Passage(NamedTuple):
    """A sentence or window with the features support_score needs, computed once."""

    text: str
    terms: frozenset[str]
    grams: Counter[str]
    norm: float
    numbers: frozenset[str]


def _passage(text: str) -> _Passage:
    grams = char_ngrams(text)
    return _Passage(
        text,
        frozenset(content_terms(text)),
        grams,
        math.sqrt(sum(v * v for v in grams.values())),
        frozenset(numbers_in(text)),
    )


@lru_cache(maxsize=64)
def _prepared_windows(paragraphs: tuple[str, ...]) -> tuple[_Passage, ...]:
    # Every sentence that cites a source is checked against the same windows, so their
    # terms and trigrams are computed once per source instead of once per sentence.
    sentences: list[str] = []
    for paragraph in paragraphs:
        sentences.extend(split_sentences(paragraph))
    windows = list(sentences)
    windows.extend(f"{a} {b}" for a, b in itertools.pairwise(sentences))
    return tuple(_passage(window) for window in windows)


def _score(claim: _Passage, passage: _Passage) -> float:
    # Same arithmetic as support_score and text.cosine, on precomputed features.
    if not claim.terms:
        return 0.0
    recall = len(claim.terms & passage.terms) / len(claim.terms)
    if not claim.grams or not passage.grams:
        similarity = 0.0
    else:
        # Counts are integers, so walking the smaller side gives the same dot product.
        small, large = sorted((claim.grams, passage.grams), key=len)
        dot = sum(count * large.get(gram, 0) for gram, count in small.items())
        norm = claim.norm * passage.norm
        similarity = dot / norm if norm else 0.0
    return round(0.75 * recall + 0.25 * similarity, 3)


def support_score(sentence: str, passage: str) -> float:
    claim_terms = set(content_terms(sentence))
    if not claim_terms:
        return 0.0
    recall = len(claim_terms & set(content_terms(passage))) / len(claim_terms)
    similarity = cosine(char_ngrams(sentence), char_ngrams(passage))
    return round(0.75 * recall + 0.25 * similarity, 3)


def best_support(sentence: str, source: Source) -> tuple[float, str, set[str]]:
    """Return (score, best passage, numbers missing from that passage)."""
    text = strip_citations(sentence)
    claim = _passage(text)
    wanted = set(claim.numbers)
    best = (0.0, "", wanted)
    for window in _prepared_windows(tuple(source.document.paragraphs)):
        score = _score(claim, window)
        missing = wanted - window.numbers
        if missing:
            score = min(score, WEAK - 0.01)
        if score > best[0]:
            best = (score, window.text, missing)
    return best


def _looks_factual(text: str) -> bool:
    return bool(numbers_in(text)) or len(text.split()) >= 8


VERIFY_PROMPT = """Passage:
\"\"\"{passage}\"\"\"

Sentence: "{sentence}"

Does the passage directly support every factual part of the sentence? Answer with one
word: SUPPORTED or UNSUPPORTED."""


def verify_sentence(
    sentence: ReportSentence, sources: dict[int, Source], llm: LLMClient | None = None
) -> ReportSentence:
    sentence.evidence = {}
    sentence.notes = []
    if not sentence.sources:
        sentence.status = "uncited" if _looks_factual(sentence.text) else "supported"
        if sentence.status == "uncited":
            sentence.notes.append("factual sentence with no citation")
        return sentence

    scores: dict[int, float] = {}
    for sid in sentence.sources:
        source = sources.get(sid)
        if source is None:
            scores[sid] = 0.0
            sentence.notes.append(f"cites unknown source id {sid}")
            continue
        score, passage, missing = best_support(sentence.text, source)
        if llm is not None and WEAK <= score < SUPPORTED and passage:
            try:
                answer = llm.complete(
                    VERIFY_PROMPT.format(passage=passage, sentence=sentence.text), max_tokens=5
                )
                if re.search(r"\bSUPPORTED\b", answer.upper()) and "UNSUPPORTED" not in answer.upper():
                    score = SUPPORTED
                    sentence.notes.append(f"{{src:{sid}}} confirmed by model check")
            except LLMError:
                pass
        scores[sid] = score
        sentence.evidence[sid] = passage
        if missing:
            sentence.notes.append(
                f"{{src:{sid}}}: number(s) {', '.join(sorted(missing))} not found in the cited text"
            )

    best = max(scores.values())
    failing = [sid for sid, s in scores.items() if s < SUPPORTED]
    sentence.support = best
    if best >= SUPPORTED and not failing:
        sentence.status = "supported"
    elif best >= SUPPORTED:
        sentence.status = "partial"
        for sid in failing:
            sentence.notes.append(f"{{src:{sid}}} does not appear to support this sentence")
    elif best >= WEAK:
        sentence.status = "weak"
        sentence.notes.append("cited text only partly matches this sentence")
    else:
        sentence.status = "unsupported"
        sentence.notes.append("cited text does not support this sentence")
    return sentence


def verify_report(report: Report, llm: LLMClient | None = None) -> Report:
    for sentence in report.all_sentences():
        verify_sentence(sentence, report.sources, llm)
    return report


def verification_summary(report: Report) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sentence in report.all_sentences():
        counts[sentence.status] = counts.get(sentence.status, 0) + 1
    return counts

"""Small, dependency free text helpers: tokenizing, stemming, sentence splitting, BM25."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence

STOPWORDS = frozenset(
    [
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "has",
        "have",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "herself",
        "him",
        "himself",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "itself",
        "just",
        "me",
        "more",
        "most",
        "my",
        "myself",
        "no",
        "nor",
        "not",
        "now",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "our",
        "ours",
        "ourselves",
        "out",
        "over",
        "own",
        "same",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "themselves",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
        "also",
        "may",
        "might",
        "must",
        "shall",
        "one",
        "per",
        "via",
        "us",
    ]
)

# Words that carry tone rather than topic. Dropped when building search queries.
QUALIFIERS = frozenset(
    [
        "actually",
        "really",
        "truly",
        "well",
        "much",
        "many",
        "good",
        "better",
        "best",
        "work",
        "works",
        "working",
        "worth",
        "exactly",
        "basically",
        "generally",
        "simply",
        "anything",
        "something",
        "everything",
        "thing",
        "things",
    ]
)

_WORD_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_NUMBER_RE = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")
_CITE_RE = re.compile(r"\s*\[(\d+(?:\s*,\s*\d+)*)\]")

_ABBREVIATIONS = frozenset(
    [
        "mr",
        "mrs",
        "ms",
        "dr",
        "prof",
        "sr",
        "jr",
        "st",
        "vs",
        "etc",
        "e.g",
        "i.e",
        "u.s",
        "u.k",
        "no",
        "fig",
        "al",
        "inc",
        "ltd",
        "co",
        "approx",
        "dept",
        "est",
    ]
)


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens. Decimals such as 0.5 stay as one token."""
    return _WORD_RE.findall(text.lower())


def stem(word: str) -> str:
    """A light suffix stripper. Good enough to match 'pumps' with 'pump' and 'saving' with 'save'."""
    if len(word) <= 3 or word[0].isdigit():
        return word
    for suffix, replacement in (
        ("ational", "ate"),
        ("ization", "ize"),
        ("iveness", "ive"),
        ("ies", "y"),
        ("ied", "y"),
        ("ing", ""),
        ("edly", ""),
        ("ed", ""),
        ("ly", ""),
        ("es", ""),
        ("s", ""),
    ):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)] + replacement
            break
    if word.endswith("e") and len(word) > 4:
        word = word[:-1]
    return word


def content_terms(text: str) -> list[str]:
    """Stemmed tokens with stopwords removed, in order."""
    return [stem(t) for t in tokenize(text) if t not in STOPWORDS]


def topic_words(text: str) -> list[str]:
    """Unstemmed, non stopword, non qualifier words in their original order, deduplicated."""
    seen: set[str] = set()
    out: list[str] = []
    for token in tokenize(text):
        if token in STOPWORDS or token in QUALIFIERS or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def numbers_in(text: str) -> set[str]:
    """Numbers as normalized strings. '1,300' and '1300' compare equal."""
    found = set()
    for match in _NUMBER_RE.findall(text):
        value = match.replace(",", "").lstrip("-")
        if value.endswith(".0"):
            value = value[:-2]
        found.add(value)
    return found


def strip_citations(text: str) -> str:
    return _CITE_RE.sub("", text).strip()


def split_sentences(text: str) -> list[str]:
    """Split prose into sentences without breaking on common abbreviations or decimals."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    sentences: list[str] = []
    start = 0
    for match in re.finditer(r"[.!?]+[\"')\]]?\s+(?=[\"'(\[]?[A-Z0-9])", text):
        end = match.end()
        candidate = text[start:end].strip()
        last_word = candidate.rstrip(".!?\"')] ").rsplit(" ", 1)[-1].lower()
        if last_word.rstrip(".") in _ABBREVIATIONS or re.fullmatch(r"[a-z]", last_word):
            continue
        sentences.append(candidate)
        start = end
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def containment(a: Iterable[str], b: Iterable[str]) -> float:
    """Share of the smaller set found in the larger one. Catches a sentence quoted inside another."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def char_ngrams(text: str, n: int = 3) -> Counter[str]:
    cleaned = " " + re.sub(r"[^a-z0-9 ]+", "", text.lower()) + " "
    return Counter(cleaned[i : i + n] for i in range(max(len(cleaned) - n + 1, 0)))


def cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(count * b.get(gram, 0) for gram, count in a.items())
    norm = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return dot / norm if norm else 0.0


def slugify(text: str, max_length: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_length].rstrip("-") or "report"


class BM25:
    """Okapi BM25 over pre-tokenized documents."""

    def __init__(self, documents: Sequence[Sequence[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs = [Counter(doc) for doc in documents]
        self.lengths = [len(doc) for doc in documents]
        self.avg_length = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        df: Counter[str] = Counter()
        for doc in self.docs:
            df.update(doc.keys())
        n = len(self.docs)
        self.idf = {term: math.log(1 + (n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()}

    def score(self, query: Sequence[str], index: int) -> float:
        doc = self.docs[index]
        length = self.lengths[index]
        total = 0.0
        for term in set(query):
            tf = doc.get(term)
            if not tf:
                continue
            denom = tf + self.k1 * (1 - self.b + self.b * length / (self.avg_length or 1))
            total += self.idf.get(term, 0.0) * tf * (self.k1 + 1) / denom
        return total

    def rank(self, query: Sequence[str]) -> list[tuple[int, float]]:
        scored = [(i, self.score(query, i)) for i in range(len(self.docs))]
        return sorted(scored, key=lambda pair: (-pair[1], pair[0]))

"""Turn a question into a handful of focused search queries.

The offline planner is rule based: it classifies the question, pulls out the topic words
and pairs them with facets that suit the question type. When an LLM is configured it is
asked for sub-queries first, and the rule based plan is the fallback.
"""

from __future__ import annotations

import json
import re

from .llm.base import LLMClient, LLMError
from .models import Plan, SubQuery
from .text import topic_words

FACETS: dict[str, list[tuple[str, str]]] = {
    "yes_no": [
        ("Evidence from studies", "{topic} evidence study findings"),
        ("Measured effects", "{topic} measured data results percent"),
        ("Background", "{topic} history origin background"),
        ("Limits and counterpoints", "{topic} criticism limitations debate"),
    ],
    "how": [
        ("How it works", "how {topic} works explained"),
        ("Performance and data", "{topic} performance efficiency data"),
        ("Practical considerations", "{topic} installation cost sizing backup"),
        ("Limits and counterpoints", "{topic} limitations problems myths"),
    ],
    "why": [
        ("Main explanations", "why {topic} reasons causes"),
        ("Evidence", "{topic} evidence research"),
        ("Background", "{topic} history background"),
        ("Counterpoints", "{topic} criticism alternative explanations"),
    ],
    "compare": [
        ("Head to head", "{topic} comparison differences"),
        ("Performance and data", "{topic} benchmark data"),
        ("Costs and trade-offs", "{topic} cost trade-offs"),
        ("When each fits", "{topic} use cases pros cons"),
    ],
    "what": [
        ("Definition and background", "what is {topic} definition background"),
        ("Key facts and data", "{topic} facts data statistics"),
        ("Current state", "{topic} recent developments"),
        ("Limits and counterpoints", "{topic} criticism limitations"),
    ],
}

_YES_NO_STARTERS = ("does", "do", "is", "are", "can", "will", "should", "was", "were", "has", "have")


def classify(question: str) -> str:
    q = question.strip().lower()
    first = q.split(" ", 1)[0] if q else ""
    if re.search(r"\b(vs\.?|versus|compared (to|with)|better than)\s", q):
        return "compare"
    if first == "which" and " or " in q:
        return "compare"
    if first == "how":
        return "how"
    if first == "why":
        return "why"
    if first in _YES_NO_STARTERS:
        return "yes_no"
    return "what"


def extract_topic(question: str) -> str:
    words = topic_words(question)
    return " ".join(words) if words else question.strip().rstrip("?")


def heuristic_plan(question: str, max_subqueries: int = 5) -> Plan:
    qtype = classify(question)
    topic = extract_topic(question)
    subqueries: list[SubQuery] = [SubQuery("Overview", topic)]
    seen = {topic}
    for facet, template in FACETS[qtype]:
        query = re.sub(r"\s+", " ", template.format(topic=topic)).strip()
        if query not in seen:
            seen.add(query)
            subqueries.append(SubQuery(facet, query))
    return Plan(question, qtype, topic, tuple(subqueries[: max(1, max_subqueries)]))


PLANNER_PROMPT = """You plan web research. Break the question into {n} short, distinct web search
queries that together cover background, evidence and counterpoints.
Return only JSON: {{"subqueries": [{{"facet": "short section title", "query": "search terms"}}]}}

Question: {question}"""


def parse_llm_plan(raw: str, question: str, max_subqueries: int) -> Plan:
    """Parse the planner model's JSON. Raises ValueError when it is unusable."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("no JSON object in planner output")
    data = json.loads(match.group(0))
    items = data.get("subqueries")
    if not isinstance(items, list):
        raise ValueError("planner output has no subqueries list")
    subqueries: list[SubQuery] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query", "")).strip()
        facet = str(item.get("facet", "")).strip() or query.title()
        if query and query.lower() not in seen:
            seen.add(query.lower())
            subqueries.append(SubQuery(facet, query))
    if not subqueries:
        raise ValueError("planner returned no usable queries")
    return Plan(question, classify(question), extract_topic(question), tuple(subqueries[:max_subqueries]))


def plan(question: str, llm: LLMClient | None = None, max_subqueries: int = 5) -> Plan:
    if not question.strip():
        raise ValueError("question is empty")
    if llm is not None:
        try:
            raw = llm.complete(PLANNER_PROMPT.format(n=max_subqueries, question=question))
            return parse_llm_plan(raw, question, max_subqueries)
        except (LLMError, ValueError, json.JSONDecodeError):
            pass
    return heuristic_plan(question, max_subqueries)

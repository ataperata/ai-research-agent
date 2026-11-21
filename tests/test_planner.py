import json

import pytest

from research_agent.planner import classify, extract_topic, heuristic_plan, parse_llm_plan, plan
from tests.conftest import FakeLLM


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Does daylight saving time actually save energy?", "yes_no"),
        ("How well do heat pumps work in cold climates?", "how"),
        ("Why did the Roman Empire fall?", "why"),
        ("Rust vs Go for command line tools", "compare"),
        ("Which is cheaper, solar or wind?", "compare"),
        ("What is a coefficient of performance?", "what"),
    ],
)
def test_classify(question, expected):
    assert classify(question) == expected


def test_topic_drops_stopwords_and_filler():
    assert (
        extract_topic("How well do heat pumps actually work in cold climates?") == "heat pumps cold climates"
    )


def test_heuristic_plan_covers_topic_and_facets():
    p = heuristic_plan("Does daylight saving time actually save energy?")
    assert p.question_type == "yes_no"
    assert p.subqueries[0].facet == "Overview"
    assert p.subqueries[0].query == "daylight saving time save energy"
    assert len(p.subqueries) == 5
    assert all("daylight saving time" in sq.query for sq in p.subqueries)
    assert len({sq.query for sq in p.subqueries}) == len(p.subqueries)
    facets = [sq.facet for sq in p.subqueries]
    assert "Limits and counterpoints" in facets


def test_plan_respects_max_and_is_deterministic():
    a = heuristic_plan("How do vaccines train the immune system?", max_subqueries=3)
    b = heuristic_plan("How do vaccines train the immune system?", max_subqueries=3)
    assert a == b and len(a.subqueries) == 3


def test_llm_plan_is_used_when_valid():
    reply = json.dumps(
        {
            "subqueries": [
                {"facet": "History", "query": "dst history"},
                {"facet": "Studies", "query": "dst electricity studies"},
                {"facet": "Dup", "query": "DST history"},
            ]
        }
    )
    llm = FakeLLM("Sure, here it is:\n" + reply)
    p = plan("Does DST save energy?", llm=llm, max_subqueries=4)
    assert [sq.query for sq in p.subqueries] == ["dst history", "dst electricity studies"]
    assert "Does DST save energy?" in llm.prompts[0]


def test_llm_plan_falls_back_on_garbage():
    p = plan("Does DST save energy?", llm=FakeLLM("I cannot help with that."))
    assert p == heuristic_plan("Does DST save energy?")


def test_parse_llm_plan_rejects_empty():
    with pytest.raises(ValueError):
        parse_llm_plan('{"subqueries": []}', "q", 5)


def test_empty_question_rejected():
    with pytest.raises(ValueError):
        plan("   ")

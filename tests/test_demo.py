import asyncio
import json
import re

import pytest

from research_agent.cli import main
from research_agent.demo import build_demo_agent, find_case, load_cases, run_demo
from research_agent.render import render_html, render_markdown


def demo_report(n):
    return asyncio.run(run_demo(load_cases()[n]))


@pytest.mark.parametrize("n", [0, 1])
def test_demo_is_deterministic(n):
    a, b = demo_report(n), demo_report(n)
    assert render_markdown(a) == render_markdown(b)
    assert render_html(a) == render_html(b)


@pytest.mark.parametrize("n", [0, 1])
def test_demo_report_is_cited_and_verified(n):
    report = demo_report(n)
    sentences = report.all_sentences()
    assert len(sentences) >= 10
    assert all(s.sources for s in sentences)
    assert all(s.status == "supported" for s in sentences)
    assert report.sections[0].title == "Key findings"
    reasons = " ".join(x.reason for x in report.exclusions)
    assert "blocked by robots.txt" in reasons
    assert "low credibility" in reasons


def test_dst_demo_contains_the_core_evidence():
    md = render_markdown(demo_report(0))
    assert "0.5 percent per day" in md
    assert "1 percent overall" in md
    assert "0.34 percent" in md
    # The sensational blog claim never reaches the report body.
    assert "10 percent or more" not in md


def test_find_case():
    assert find_case("2").slug == "heat-pumps-cold-climates"
    assert find_case("daylight saving energy").slug == "daylight-saving-energy"
    with pytest.raises(ValueError, match="Available demos"):
        find_case("quantum gravity")


def test_demo_uses_no_real_network(monkeypatch):
    import httpx

    def refuse(*args, **kwargs):
        raise AssertionError("demo tried to open a real connection")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)
    agent, client = build_demo_agent(load_cases()[0])

    async def go():
        async with client:
            return await agent.run(load_cases()[0].question)

    assert asyncio.run(go()).sources


def test_llm_path_output_is_still_verified(fake_llm):
    """A model that cites the wrong source gets caught by the verifier."""
    case = load_cases()[0]
    plan_reply = json.dumps(
        {"subqueries": [{"facet": "Evidence", "query": "daylight saving time electricity study"}]}
    )
    synth = {
        "sections": [
            {
                "title": "Key findings",
                "bullets": True,
                "sentences": [
                    {
                        "text": "Kotchen and Grant found that daylight saving time increased residential electricity demand in Indiana by about 1 percent overall.",
                        "sources": [1],
                    },
                    {"text": "Daylight saving time cuts energy use by 10 percent or more.", "sources": [2]},
                ],
            }
        ]
    }
    agent, client = build_demo_agent(case)
    agent.llm = fake_llm(plan_reply, json.dumps(synth), *["UNSUPPORTED"] * 10)

    async def run_it():
        async with client:
            return await agent.run(case.question)

    report = asyncio.run(run_it())
    by_text = {s.text: s for s in report.all_sentences()}
    bogus = by_text["Daylight saving time cuts energy use by 10 percent or more."]
    assert bogus.flagged
    assert report.plan.subqueries[0].query == "daylight saving time electricity study"


def test_cli_demo_writes_files(tmp_path, capsys):
    code = main(["--demo", "2", "-o", str(tmp_path), "--strict"])
    assert code == 0
    md = (tmp_path / "heat-pumps-cold-climates.md").read_text()
    html = (tmp_path / "heat-pumps-cold-climates.html").read_text()
    assert md.startswith("# How well do heat pumps work in cold climates?")
    assert "<!DOCTYPE html>" in html and 'class="tip"' in html
    out = capsys.readouterr().out
    assert re.search(r"\[\d\]", out)


def test_cli_without_question_or_keys_fails_cleanly(monkeypatch, capsys):
    for var in ("TAVILY_API_KEY", "BRAVE_API_KEY", "SERPAPI_API_KEY", "RESEARCH_SEARCH"):
        monkeypatch.delenv(var, raising=False)
    assert main([]) == 1
    assert main(["Is coffee good for you?", "--no-cache", "--llm", "none"]) == 1
    assert "research --demo" in capsys.readouterr().err

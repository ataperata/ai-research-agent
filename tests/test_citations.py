from research_agent.models import ReportSentence, Section
from research_agent.render import number_sources, render_html, render_markdown
from research_agent.render.common import format_note
from tests.conftest import make_report, make_source


def _report():
    sources = [make_source(i, [f"Paragraph from source {i} about heat pumps."]) for i in (1, 2, 3, 4)]
    sections = [
        Section(
            "Key findings",
            [
                ReportSentence("First claim.", [3]),
                ReportSentence("Second claim.", [1, 3]),
            ],
            bullets=True,
        ),
        Section(
            "Details",
            [
                ReportSentence("Third claim.", [2, 1]),
                ReportSentence("Bogus id is ignored.", [99, 3]),
            ],
        ),
    ]
    return make_report(sections, sources)


def test_numbers_follow_first_appearance():
    report = _report()
    assert number_sources(report) == {3: 1, 1: 2, 2: 3}


def test_markdown_citations_are_sorted_and_sequential():
    md = render_markdown(_report())
    assert "- First claim. [1]" in md
    assert "- Second claim. [1][2]" in md
    assert "Third claim. [2][3]" in md
    assert "Bogus id is ignored. [1]" in md
    # Reference list is in citation order and only lists cited sources.
    refs = md.split("## Sources")[1]
    assert refs.index("1. [Source 3]") < refs.index("2. [Source 1]") < refs.index("3. [Source 2]")
    assert "Also read but not cited" in refs and "Source 4" in refs


def test_every_number_in_text_has_a_reference():
    import re

    md = render_markdown(_report())
    body, refs = md.split("## Sources")
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", body.split("## Verification")[0])}
    listed = {int(n) for n in re.findall(r"^(\d+)\. \[", refs, re.M)}
    assert cited == listed == {1, 2, 3}


def test_notes_use_citation_numbers():
    assert format_note("{src:2} does not support this", {2: 3}) == "[3] does not support this"


def test_html_has_hover_tooltips_and_anchors():
    html = render_html(_report())
    assert html.count('class="cite"') == 6
    assert 'href="#src-1"' in html and 'id="src-3"' in html
    assert 'class="tip"' in html

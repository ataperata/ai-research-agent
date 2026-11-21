from research_agent.models import ReportSentence, Section
from research_agent.render import render_markdown
from research_agent.verify import verify_report, verify_sentence
from tests.conftest import FakeLLM, make_report, make_source

DOE = make_source(
    1,
    [
        "The report estimated that the extension reduced total electricity use by about 0.5 percent "
        "per day. Savings were largest in the evening hours."
    ],
)
INDIANA = make_source(
    2,
    [
        "Researchers found that daylight saving time increased residential electricity demand by about 1 percent."
    ],
)
SOURCES = {1: DOE, 2: INDIANA}


def check(text, sources):
    return verify_sentence(ReportSentence(text, sources), SOURCES)


def test_supported_sentence_passes():
    s = check("The extension reduced total electricity use by about 0.5 percent per day.", [1])
    assert s.status == "supported" and not s.flagged
    assert "0.5 percent" in s.evidence[1]


def test_wrong_source_is_flagged():
    s = check("The extension reduced total electricity use by about 0.5 percent per day.", [2])
    assert s.status == "unsupported" and s.flagged


def test_changed_number_is_flagged_even_when_words_match():
    s = check("The extension reduced total electricity use by about 5 percent per day.", [1])
    assert s.flagged
    assert any("number(s) 5 not found" in note for note in s.notes)


def test_one_bad_citation_among_good_ones_is_flagged():
    s = check("The extension reduced total electricity use by about 0.5 percent per day.", [1, 2])
    assert s.status == "partial" and s.flagged
    assert any("{src:2}" in note for note in s.notes)


def test_uncited_factual_sentence_is_flagged():
    s = check("Daylight saving time cut demand by 12 percent in every state.", [])
    assert s.status == "uncited" and s.flagged


def test_unrelated_claim_is_flagged():
    s = check("Heat pumps keep working at minus thirteen degrees Fahrenheit.", [1])
    assert s.status == "unsupported"


def test_llm_can_confirm_a_borderline_sentence():
    text = "Evening hours saw the biggest savings from the change."
    plain = check(text, [1])
    assert plain.status == "weak"
    confirmed = verify_sentence(ReportSentence(text, [1]), SOURCES, llm=FakeLLM("SUPPORTED"))
    assert confirmed.status == "supported"
    rejected = verify_sentence(ReportSentence(text, [1]), SOURCES, llm=FakeLLM("UNSUPPORTED"))
    assert rejected.status == "weak"


def test_flagged_sentences_appear_in_markdown_verification_table():
    report = make_report(
        [
            Section(
                "Findings",
                [
                    ReportSentence(
                        "The extension reduced total electricity use by about 0.5 percent per day.", [1]
                    ),
                    ReportSentence(
                        "The extension reduced total electricity use by about 0.5 percent per day.", [2]
                    ),
                ],
            )
        ],
        [DOE, INDIANA],
    )
    verify_report(report)
    md = render_markdown(report)
    assert "1 of 2 sentences were flagged" in md
    assert "**(flagged)**" in md
    assert "not supported by citation" in md


def test_best_support_matches_a_plain_scan_of_every_window():
    import itertools

    from research_agent.text import numbers_in, split_sentences, strip_citations
    from research_agent.verify import WEAK, best_support, support_score

    def reference(sentence, source):
        text = strip_citations(sentence)
        wanted = numbers_in(text)
        sentences = [s for p in source.document.paragraphs for s in split_sentences(p)]
        windows = sentences + [f"{a} {b}" for a, b in itertools.pairwise(sentences)]
        best = (0.0, "", wanted)
        for window in windows:
            score = support_score(text, window)
            missing = wanted - numbers_in(window)
            if missing:
                score = min(score, WEAK - 0.01)
            if score > best[0]:
                best = (score, window, missing)
        return best

    claims = [
        "The extension reduced total electricity use by about 0.5 percent per day. [1]",
        "Savings were largest in the evening hours. [1]",
        "Demand rose by about 3 percent. [2]",
        "Daylight saving time increased residential electricity demand. [2]",
        "Unrelated words entirely.",
    ]
    for claim in claims:
        for source in SOURCES.values():
            assert best_support(claim, source) == reference(claim, source)

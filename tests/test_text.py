from research_agent.text import (
    BM25,
    content_terms,
    numbers_in,
    slugify,
    split_sentences,
    stem,
    strip_citations,
)


def test_split_sentences_respects_abbreviations_and_decimals():
    text = (
        "The U.S. report found a 0.5 percent drop. Dr. Smith agreed, e.g. in 2008. "
        "Savings were small! Were they real? Yes."
    )
    assert split_sentences(text) == [
        "The U.S. report found a 0.5 percent drop.",
        "Dr. Smith agreed, e.g. in 2008.",
        "Savings were small!",
        "Were they real?",
        "Yes.",
    ]


def test_numbers_are_normalized():
    assert numbers_in("About 1,300 homes, 0.5 percent, $9 million, -13°F") == {"1300", "0.5", "9", "13"}


def test_stem_matches_simple_variants():
    assert stem("pumps") == stem("pump")
    assert stem("studies") == stem("study")
    assert stem("saving") == stem("saves") == "sav"


def test_content_terms_drop_stopwords():
    assert content_terms("How do the heat pumps work?") == ["heat", "pump", "work"]


def test_strip_citations_and_slugify():
    assert strip_citations("Demand rose 1 percent [1][2, 3].") == "Demand rose 1 percent."
    assert slugify("Does DST save energy?") == "does-dst-save-energy"


def test_bm25_ranks_relevant_document_first():
    docs = [content_terms("cats and dogs"), content_terms("heat pump efficiency in cold weather")]
    ranked = BM25(docs).rank(content_terms("cold heat pump"))
    assert ranked[0][0] == 1 and ranked[0][1] > ranked[1][1]

from research_agent.credibility import score_document
from research_agent.fetch.extract import extract
from research_agent.models import Document

HTML = """<!DOCTYPE html><html><head><title>Heat Pump Basics | Energy Office</title>
<meta name="author" content="Jane Doe"><meta property="article:published_time" content="2023-06-01">
<script>var tracking = "Lorem ipsum, dolor, sit, amet, tracking code here";</script></head>
<body><header><nav><a href="/">Home</a><a href="/about">About us and our long mission statement</a></nav></header>
<div id="cookie-banner">We use cookies to improve your experience, measure traffic, and show ads.</div>
<div class="layout"><article class="post-content"><h1>Heat Pump Basics</h1>
<p>A heat pump moves heat from one place to another instead of burning fuel, which is why it can be so efficient.
<p>Even cold air contains heat energy, so a refrigerant can absorb it outdoors and release it inside.</p>
<p>Short.</p>
<h2>References</h2><ol class="references"><li>Department of Energy, Energy Saver, Heat Pump Systems, 2023.</li></ol>
</article><aside class="sidebar"><p>Related: ten tips to save money on your power bill this winter season.</p></aside></div>
<footer><p>Copyright Energy Office. Privacy policy. Accessibility statement and more links.</p></footer>
</body></html>"""


def test_extract_keeps_article_and_drops_chrome():
    doc = extract(HTML, "https://energy.example.gov/basics")
    assert doc.title == "Heat Pump Basics"
    assert doc.author == "Jane Doe"
    assert doc.published == "2023-06-01"
    assert doc.has_references
    assert doc.paragraphs == [
        "A heat pump moves heat from one place to another instead of burning fuel, which is why it can be so efficient.",
        "Even cold air contains heat energy, so a refrigerant can absorb it outdoors and release it inside.",
    ]
    text = doc.text
    for junk in ("cookies", "Copyright", "Related:", "tracking", "Department of Energy"):
        assert junk not in text


def _doc(url, paragraphs, **kw):
    return Document(url=url, title="t", paragraphs=paragraphs, **kw)


LONG = ["Measured results from several winters of monitoring show steady performance. " * 12]


def test_government_outranks_blog():
    gov = score_document(
        _doc("https://x.gov/a", LONG, author="A", published="2023-01-01", has_references=True), 2026
    )
    blog = score_document(_doc("https://my-blog.com/a", LONG), 2026)
    assert gov.score > 0.8 and gov.label == "high"
    assert blog.score < gov.score
    assert any("blog" in r for r in blog.reasons)


def test_sensational_language_is_penalized():
    calm = score_document(_doc("https://news.example.com/a", LONG, published="2024-01-01"), 2026)
    loud = score_document(
        _doc(
            "https://news.example.com/b",
            [LONG[0] + " Everybody knows this. SHOCKING results!!"],
            published="2024-01-01",
        ),
        2026,
    )
    assert loud.score < calm.score
    assert any("sensational" in r for r in loud.reasons)


def test_demo_test_tld_scores_like_real_tld():
    a = score_document(_doc("https://energy.gov.test/a", LONG), 2026)
    b = score_document(_doc("https://energy.gov/a", LONG), 2026)
    assert a.score == b.score

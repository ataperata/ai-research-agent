"""Web front end for the offline demo, used for hosted deploys such as Vercel.

It serves a landing page and runs the real research pipeline on the bundled
corpus for each request. No API keys and no outbound network are needed.

Run it locally with:  python app.py   (then open http://127.0.0.1:8000)
"""

from __future__ import annotations

import asyncio
import html
import sys
from pathlib import Path
from wsgiref.simple_server import make_server

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from research_agent import __version__
from research_agent.demo import load_cases, run_demo
from research_agent.render import render_html, render_markdown

CASES = {case.slug: case for case in load_cases()}

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ai-research-agent · live demo</title>
<style>
  :root {{ color-scheme: light dark; --ink:#1b1f24; --dim:#5b6470; --line:#d9dee5; --acc:#2a6df4; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --ink:#e8ecf2; --dim:#9aa4b2; --line:#2b313a; --acc:#6ea0ff; }} body {{ background:#0f1216; }} }}
  body {{ font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color: var(--ink); max-width: 760px; margin: 0 auto; padding: 48px 20px; }}
  h1 {{ font-size: 30px; margin: 0 0 6px; }}
  p.lede {{ color: var(--dim); margin: 0 0 32px; }}
  .card {{ border: 1px solid var(--line); border-radius: 12px; padding: 18px 20px; margin: 0 0 14px; }}
  .card h2 {{ font-size: 18px; margin: 0 0 10px; }}
  a.btn {{ display: inline-block; padding: 8px 14px; border-radius: 8px; background: var(--acc); color: #fff; text-decoration: none; font-weight: 600; margin-right: 8px; }}
  a.ghost {{ background: transparent; color: var(--acc); border: 1px solid var(--line); }}
  ol {{ color: var(--dim); padding-left: 20px; }}
  footer {{ margin-top: 40px; color: var(--dim); font-size: 13px; }}
</style>
</head>
<body>
<h1>ai-research-agent</h1>
<p class="lede">Ask a question, get a report where every sentence carries a numbered citation, then a verifier
checks each sentence against the source it cites. This hosted demo runs the real pipeline on a bundled
corpus, so it needs no keys and makes no outside requests.</p>
{cards}
<h3>What happens when you press Run</h3>
<ol>
  <li>The planner splits the question into sub-queries.</li>
  <li>The fetcher reads each page, honoring robots.txt and a per-domain rate limit.</li>
  <li>Sources are scored for credibility and weak ones are dropped.</li>
  <li>Claims are extracted, written up with citations, and every sentence is verified.</li>
</ol>
<footer>v{version} · <a href="https://github.com/ataperata/ai-research-agent">source on GitHub</a></footer>
</body>
</html>
"""

CARD = """<div class="card">
  <h2>{question}</h2>
  <a class="btn" href="/report/{slug}">Run the research</a>
  <a class="btn ghost" href="/report/{slug}.md">Markdown</a>
</div>"""


def _landing() -> str:
    cards = "\n".join(
        CARD.format(question=html.escape(c.question), slug=html.escape(slug)) for slug, c in CASES.items()
    )
    return PAGE.format(cards=cards, version=html.escape(__version__))


def _respond(start_response, status: str, body: str, ctype: str = "text/html; charset=utf-8"):
    data = body.encode("utf-8")
    start_response(
        status,
        [
            ("Content-Type", ctype),
            ("Content-Length", str(len(data))),
            ("Cache-Control", "public, max-age=300"),
            ("X-Content-Type-Options", "nosniff"),
        ],
    )
    return [data]


def app(environ, start_response):
    """WSGI entry point."""
    method = environ.get("REQUEST_METHOD", "GET")
    path = environ.get("PATH_INFO", "/") or "/"
    if method not in ("GET", "HEAD"):
        return _respond(start_response, "405 Method Not Allowed", "Method not allowed", "text/plain")
    if path == "/":
        return _respond(start_response, "200 OK", _landing())
    if path == "/healthz":
        return _respond(start_response, "200 OK", "ok", "text/plain")
    if path.startswith("/report/"):
        name = path[len("/report/") :]
        as_md = name.endswith(".md")
        slug = name[:-3] if as_md else name
        case = CASES.get(slug)
        if case is None:
            return _respond(start_response, "404 Not Found", "No such demo question", "text/plain")
        report = asyncio.run(run_demo(case))
        if as_md:
            return _respond(start_response, "200 OK", render_markdown(report), "text/markdown; charset=utf-8")
        return _respond(start_response, "200 OK", render_html(report))
    return _respond(start_response, "404 Not Found", "Not found", "text/plain")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"serving on http://127.0.0.1:{port}")
    make_server("127.0.0.1", port, app).serve_forever()

"""Command line entry point: `research "question"` or `research --demo`."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

import httpx

from . import USER_AGENT, __version__
from .cache import Cache
from .fetch.fetcher import Fetcher
from .fetch.ratelimit import DomainRateLimiter
from .llm.base import LLMClient
from .llm.providers import llm_from_env
from .models import Report
from .pipeline import ResearchAgent, Settings
from .render import render_html, render_markdown
from .search.providers import CachedSearch, SearchError, provider_from_env
from .text import slugify


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="research",
        description="Research a question on the web and write a cited, verified report.",
    )
    p.add_argument("question", nargs="?", help="the question to research")
    p.add_argument(
        "--demo", action="store_true", help="run offline on the bundled corpus (no keys, no network)"
    )
    p.add_argument("--list-demos", action="store_true", help="list the bundled demo questions")
    p.add_argument("-o", "--out", default="reports", help="output directory (default: reports)")
    p.add_argument("--format", default="md,html", help="comma separated: md, html (default: md,html)")
    p.add_argument("--search", choices=["tavily", "brave", "serpapi"], help="search provider")
    p.add_argument(
        "--llm", choices=["anthropic", "openai", "none"], help="LLM provider, or none for extractive mode"
    )
    p.add_argument("--max-sources", type=int, default=10, help="pages to read (default: 10)")
    p.add_argument("--subqueries", type=int, default=5, help="search queries to plan (default: 5)")
    p.add_argument("--min-credibility", type=float, default=0.40, help="drop sources scoring below this")
    p.add_argument("--rate-limit", type=float, default=1.0, help="seconds between requests to one domain")
    p.add_argument(
        "--cache-dir", default="~/.cache/ai-research-agent", help="where pages and searches are cached"
    )
    p.add_argument("--no-cache", action="store_true", help="do not read or write the cache")
    p.add_argument("--strict", action="store_true", help="exit with status 2 if any sentence is flagged")
    p.add_argument("-q", "--quiet", action="store_true", help="do not print the report or progress")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def write_outputs(report: Report, out_dir: Path, formats: set[str], slug: str) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    if "md" in formats:
        path = out_dir / f"{slug}.md"
        path.write_text(render_markdown(report), "utf-8")
        written.append(path)
    if "html" in formats:
        path = out_dir / f"{slug}.html"
        path.write_text(render_html(report), "utf-8")
        written.append(path)
    return written


async def run_live(args: argparse.Namespace, log) -> Report:
    llm: LLMClient | None = llm_from_env(args.llm)
    log(f"llm: {llm.name + ' ' + llm.model if llm else 'none (extractive mode)'}")
    cache = Cache(None if args.no_cache else args.cache_dir)
    async with httpx.AsyncClient(timeout=20) as client:
        provider = CachedSearch(provider_from_env(client, args.search), cache)
        log(f"search: {provider.name}")
        fetcher = Fetcher(
            client, user_agent=USER_AGENT, cache=cache, limiter=DomainRateLimiter(args.rate_limit)
        )
        settings = Settings(
            max_subqueries=args.subqueries,
            max_sources=args.max_sources,
            min_credibility=args.min_credibility,
        )
        agent = ResearchAgent(provider, fetcher, llm=llm, settings=settings, mode="live", log=log)
        report = await agent.run(args.question)
    report.generated = date.today().isoformat()
    return report


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    formats = {f.strip().lower() for f in args.format.split(",") if f.strip()}

    def log(message: str) -> None:
        if not args.quiet:
            print(f"  {message}", file=sys.stderr)

    if args.list_demos:
        from .demo import load_cases

        for i, case in enumerate(load_cases(), 1):
            print(f"{i}. {case.question}")
        return 0

    reports: list[tuple[Report, str]] = []
    if args.demo:
        from .demo import find_case, load_cases, run_demo

        try:
            cases = [find_case(args.question)] if args.question else load_cases()
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        for case in cases:
            log(f"demo: {case.question}")
            reports.append((asyncio.run(run_demo(case, log)), case.slug))
    else:
        if not args.question:
            build_parser().print_usage(sys.stderr)
            print("error: give a question, or use --demo", file=sys.stderr)
            return 1
        try:
            reports.append((asyncio.run(run_live(args, log)), slugify(args.question)))
        except (SearchError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    any_flagged = False
    for report, slug in reports:
        if not report.sources:
            print(f"error: no usable sources for {report.question!r}", file=sys.stderr)
            return 1
        paths = write_outputs(report, Path(args.out), formats, slug)
        any_flagged |= any(s.flagged for s in report.all_sentences())
        if not args.quiet:
            print(render_markdown(report))
        for path in paths:
            print(f"wrote {path}", file=sys.stderr)
    return 2 if (args.strict and any_flagged) else 0


if __name__ == "__main__":
    raise SystemExit(main())

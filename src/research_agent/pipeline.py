"""Wire the stages together: plan, search, fetch, score, extract, write, verify."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from . import planner
from .claims import extract_claims
from .credibility import score_document
from .fetch.fetcher import Fetcher
from .llm.base import LLMClient, LLMError
from .models import Exclusion, Report, SearchResult, Source
from .search.providers import SearchError, SearchProvider
from .synthesize import synthesize_extractive, synthesize_llm
from .verify import verify_report


@dataclass
class Settings:
    max_subqueries: int = 5
    results_per_query: int = 5
    max_sources: int = 10
    min_credibility: float = 0.40
    summary_size: int = 4
    per_section: int = 4
    reference_year: int | None = None


class ResearchAgent:
    def __init__(
        self,
        search: SearchProvider,
        fetcher: Fetcher,
        *,
        llm: LLMClient | None = None,
        settings: Settings | None = None,
        mode: str = "live",
        log: Callable[[str], None] | None = None,
    ):
        self.search = search
        self.fetcher = fetcher
        self.llm = llm
        self.settings = settings or Settings()
        self.mode = mode
        self.log = log or (lambda _msg: None)

    async def _gather_results(self, plan: planner.Plan) -> list[tuple[SearchResult, list[str]]]:
        found: dict[str, tuple[SearchResult, list[str], tuple[int, int]]] = {}
        errors = 0
        # The sub-queries are independent, so they go out together. gather keeps plan
        # order, so the merge below, the log and the report match a sequential run.
        outcomes = await asyncio.gather(
            *(self.search.search(sq.query, self.settings.results_per_query) for sq in plan.subqueries),
            return_exceptions=True,
        )
        for qi, (sq, results) in enumerate(zip(plan.subqueries, outcomes, strict=True)):
            if isinstance(results, SearchError):
                errors += 1
                self.log(f"search failed for {sq.query!r}: {results}")
                continue
            if isinstance(results, BaseException):
                raise results
            self.log(f"search [{sq.facet}] {sq.query!r}: {len(results)} results")
            for rank, result in enumerate(results):
                if result.url in found:
                    found[result.url][1].append(sq.facet)
                else:
                    found[result.url] = (result, [sq.facet], (rank, qi))
        if errors == len(plan.subqueries):
            raise SearchError("every search query failed")
        # Interleave by rank so each sub-query gets its top hits in before anyone's second hit.
        ordered = sorted(found.values(), key=lambda item: item[2])
        return [(result, facets) for result, facets, _ in ordered[: self.settings.max_sources]]

    async def run(self, question: str) -> Report:
        s = self.settings
        plan = planner.plan(question, self.llm, s.max_subqueries)
        self.log(f"plan: {len(plan.subqueries)} sub-queries ({plan.question_type})")

        hits = await self._gather_results(plan)
        results = await self.fetcher.fetch_many([hit.url for hit, _ in hits])

        sources: dict[int, Source] = {}
        exclusions: list[Exclusion] = []
        for (hit, facets), fetched in zip(hits, results, strict=True):
            if not fetched.ok or fetched.document is None:
                exclusions.append(Exclusion(hit.url, fetched.error or "fetch failed"))
                self.log(f"skip {hit.url}: {fetched.error}")
                continue
            credibility = score_document(fetched.document, s.reference_year)
            if credibility.score < s.min_credibility:
                reasons = ", ".join(r for r in credibility.reasons if r.startswith("-"))
                exclusions.append(Exclusion(hit.url, f"low credibility ({credibility.score:.2f}): {reasons}"))
                self.log(f"exclude {hit.url}: credibility {credibility.score:.2f}")
                continue
            sid = len(sources) + 1
            sources[sid] = Source(sid, fetched.document, credibility, facets)
            cached = " (cache)" if fetched.from_cache else ""
            self.log(f"read {hit.url}{cached}: credibility {credibility.label} {credibility.score:.2f}")

        report = Report(question, [], sources, plan, exclusions, mode=self.mode)
        if not sources:
            self.log("no usable sources found")
            return report

        claims = extract_claims(plan, list(sources.values()))
        self.log(f"claims: {len(claims)} candidates")
        if self.llm is not None:
            try:
                report.sections = synthesize_llm(plan, claims, sources, self.llm)
            except LLMError as exc:
                self.log(f"LLM synthesis failed ({exc}); using extractive writer")
        if not report.sections:
            report.sections = synthesize_extractive(
                plan, claims, sources, summary_size=s.summary_size, per_section=s.per_section
            )
        verify_report(report, self.llm)
        flagged = sum(1 for x in report.all_sentences() if x.flagged)
        self.log(f"verify: {len(report.all_sentences())} sentences, {flagged} flagged")
        return report

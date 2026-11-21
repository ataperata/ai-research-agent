"""Helpers shared by the Markdown and HTML renderers."""

from __future__ import annotations

import re

from ..models import Report

STATUS_LABELS = {
    "supported": "supported",
    "partial": "one citation does not match",
    "weak": "weak support",
    "unsupported": "not supported by citation",
    "uncited": "missing citation",
    "unchecked": "not checked",
}


def number_sources(report: Report) -> dict[int, int]:
    """Map source id to citation number in order of first appearance in the report."""
    numbers: dict[int, int] = {}
    for sentence in report.all_sentences():
        for sid in sentence.sources:
            if sid in report.sources and sid not in numbers:
                numbers[sid] = len(numbers) + 1
    return numbers


def citation_numbers(source_ids: list[int], numbers: dict[int, int]) -> list[int]:
    return sorted({numbers[sid] for sid in source_ids if sid in numbers})


def format_note(note: str, numbers: dict[int, int]) -> str:
    return re.sub(r"\{src:(\d+)\}", lambda m: f"[{numbers.get(int(m.group(1)), '?')}]", note)


def uncited_sources(report: Report, numbers: dict[int, int]) -> list[int]:
    return [sid for sid in sorted(report.sources) if sid not in numbers]

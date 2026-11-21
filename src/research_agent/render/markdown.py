"""Render a verified report as Markdown with numbered citations."""

from __future__ import annotations

from ..models import Report
from ..verify import verification_summary
from .common import STATUS_LABELS, citation_numbers, format_note, number_sources, uncited_sources


def _cite(source_ids: list[int], numbers: dict[int, int]) -> str:
    return "".join(f"[{n}]" for n in citation_numbers(source_ids, numbers))


def render_markdown(report: Report) -> str:
    numbers = number_sources(report)
    sentences = report.all_sentences()
    counts = verification_summary(report)
    supported = counts.get("supported", 0)
    flagged = [s for s in sentences if s.flagged]

    lines = [f"# {report.question}", ""]
    meta = [
        f"Mode: {report.mode}",
        f"{len(numbers)} sources cited",
        f"{len(report.exclusions)} excluded",
        f"verification: {supported}/{len(sentences)} sentences supported",
    ]
    if report.generated:
        meta.insert(1, f"generated {report.generated}")
    lines += ["_" + " · ".join(meta) + "_", ""]

    for section in report.sections:
        lines += [f"## {section.title}", ""]
        if section.bullets:
            for s in section.sentences:
                mark = " **(flagged)**" if s.flagged else ""
                lines.append(f"- {s.text} {_cite(s.sources, numbers)}{mark}".rstrip())
        else:
            parts = []
            for s in section.sentences:
                mark = " **(flagged)**" if s.flagged else ""
                parts.append(f"{s.text} {_cite(s.sources, numbers)}{mark}".rstrip())
            lines.append(" ".join(parts))
        lines.append("")

    lines += ["## Verification", ""]
    if not flagged:
        lines.append(
            f"All {len(sentences)} sentences were checked against the text of the sources they cite "
            "and every one was supported."
        )
    else:
        lines.append(f"{len(flagged)} of {len(sentences)} sentences were flagged. Treat these with care:")
        lines.append("")
        lines.append("| Sentence | Problem |")
        lines.append("| --- | --- |")
        for s in flagged:
            notes = "; ".join(format_note(n, numbers) for n in s.notes) or STATUS_LABELS[s.status]
            text = s.text.replace("|", "\\|")
            lines.append(f"| {text} {_cite(s.sources, numbers)} | {STATUS_LABELS[s.status]}: {notes} |")
    lines.append("")

    lines += ["## Sources", ""]
    by_number = sorted(numbers.items(), key=lambda kv: kv[1])
    for sid, n in by_number:
        source = report.sources[sid]
        cred = source.credibility
        lines.append(
            f"{n}. [{source.title}]({source.url}) ({source.document.domain}). "
            f"Credibility {cred.label} ({cred.score:.2f}): {', '.join(cred.reasons) or 'no signals'}."
        )
    extra = uncited_sources(report, numbers)
    if extra:
        lines += ["", "Also read but not cited:", ""]
        for sid in extra:
            source = report.sources[sid]
            lines.append(f"- [{source.title}]({source.url}), credibility {source.credibility.label}")
    lines.append("")

    if report.exclusions:
        lines += ["## Excluded sources", ""]
        for item in report.exclusions:
            lines.append(f"- {item.url}: {item.reason}")
        lines.append("")

    lines += ["## Method", "", f"Question type: {report.plan.question_type}. Search queries:", ""]
    for sq in report.plan.subqueries:
        lines.append(f"- {sq.facet}: `{sq.query}`")
    lines.append("")
    return "\n".join(lines)

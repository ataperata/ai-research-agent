"""Render a verified report as a single self-contained HTML page with hover citations."""

from __future__ import annotations

from html import escape

from ..models import Report, ReportSentence, Source
from ..verify import verification_summary
from .common import STATUS_LABELS, citation_numbers, format_note, number_sources, uncited_sources

CSS = """
:root{--ink:#1d2330;--muted:#5f6878;--line:#e3e6ec;--bg:#fbfaf7;--card:#fff;--accent:#2d5bd7;
--ok:#1f8a4c;--warn:#b7791f;--bad:#c53030;--high:#1f8a4c;--medium:#b7791f;--low:#c53030}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.65 Charter,"Iowan Old Style",Georgia,serif}
.wrap{max-width:1180px;margin:0 auto;padding:40px 28px 80px;display:grid;
grid-template-columns:minmax(0,1fr) 330px;gap:48px}
header{grid-column:1/-1;border-bottom:1px solid var(--line);padding-bottom:22px}
.eyebrow{font:600 12px/1 ui-sans-serif,system-ui,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:var(--accent)}
h1{font-size:34px;line-height:1.2;margin:10px 0 14px;letter-spacing:-.01em}
.chips{display:flex;flex-wrap:wrap;gap:8px;font:13px/1 ui-sans-serif,system-ui,sans-serif}
.chip{border:1px solid var(--line);background:var(--card);border-radius:999px;padding:7px 12px;color:var(--muted)}
.chip b{color:var(--ink)}
.meter{display:inline-block;width:70px;height:6px;border-radius:3px;background:#eadfdf;vertical-align:middle;margin-left:6px;overflow:hidden}
.meter i{display:block;height:100%;background:var(--ok)}
main h2{font-size:22px;margin:34px 0 10px;letter-spacing:-.005em}
main ul{padding-left:22px}
main li{margin:8px 0}
.s{border-radius:3px;transition:background .15s}
.verify-on .s.supported{background:rgba(31,138,76,.09)}
.s.flagged{text-decoration:underline wavy var(--warn);text-underline-offset:4px}
.s.unsupported.flagged,.s.uncited.flagged{text-decoration-color:var(--bad)}
.cite{position:relative;display:inline-block;font:600 11px/1 ui-sans-serif,system-ui,sans-serif;
color:var(--accent);background:#eaf0ff;border-radius:4px;padding:3px 5px;margin-left:2px;
vertical-align:super;cursor:pointer;text-decoration:none}
.cite:hover,.cite:focus{background:var(--accent);color:#fff;outline:none}
.tip{visibility:hidden;opacity:0;position:absolute;z-index:20;top:calc(100% + 10px);left:-12px;width:360px;
background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:10px;
box-shadow:0 12px 32px rgba(20,30,60,.16);padding:14px 16px;font:13.5px/1.5 ui-sans-serif,system-ui,sans-serif;
text-align:left;transition:opacity .12s;white-space:normal;vertical-align:baseline}
.tip.flip{left:auto;right:-12px}
.cite:hover .tip,.cite:focus .tip{visibility:visible;opacity:1}
.tip .t{font-weight:650;font-size:14px;display:block;margin-bottom:2px}
.tip .d{color:var(--muted);display:block;margin-bottom:8px}
.tip q{display:block;quotes:none;border-left:3px solid var(--accent);padding:4px 0 4px 10px;
margin:8px 0;color:#2b3242;font-family:Charter,Georgia,serif;font-size:14px}
.tip .row{display:flex;justify-content:space-between;color:var(--muted);font-size:12px}
.badge{font:600 11px/1 ui-sans-serif,system-ui,sans-serif;border-radius:999px;padding:4px 8px;text-transform:uppercase;letter-spacing:.05em}
.badge.high{background:#e3f4ea;color:var(--high)}.badge.medium{background:#fbf0dc;color:var(--medium)}
.badge.low{background:#fbe3e3;color:var(--low)}
aside{font:14px/1.5 ui-sans-serif,system-ui,sans-serif}
.panel{position:sticky;top:20px}
.panel h3{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin:0 0 12px}
.src{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:10px;scroll-margin-top:20px}
.src:target{border-color:var(--accent);box-shadow:0 0 0 3px #dfe7ff}
.src .n{font-weight:700;color:var(--accent);margin-right:6px}
.src a{color:var(--ink);font-weight:600;text-decoration:none}
.src a:hover{text-decoration:underline}
.src .dom{color:var(--muted);font-size:12.5px;margin:3px 0 8px}
.bar{height:5px;border-radius:3px;background:#eef0f4;overflow:hidden;margin:6px 0}
.bar i{display:block;height:100%}
.why{color:var(--muted);font-size:12px}
.toggle{display:flex;align-items:center;gap:8px;margin:0 0 18px;color:var(--muted);cursor:pointer;user-select:none}
.flags{background:#fff8eb;border:1px solid #f1dfb5;border-radius:10px;padding:12px 16px;font:14px/1.5 ui-sans-serif,system-ui,sans-serif}
.flags.clean{background:#eef8f2;border-color:#cfe8d9}
.foot{font:14px/1.6 ui-sans-serif,system-ui,sans-serif;color:var(--muted)}
.foot code{background:#f0f1f4;border-radius:4px;padding:1px 5px;font-size:12.5px}
@media (max-width:900px){.wrap{grid-template-columns:1fr}.panel{position:static}}
"""

JS = """
document.getElementById('vt').addEventListener('change',e=>{
  document.body.classList.toggle('verify-on',e.target.checked)});
document.querySelectorAll('.cite').forEach(c=>{c.addEventListener('mouseenter',()=>{
  const t=c.querySelector('.tip');t.classList.remove('flip');
  if(t.getBoundingClientRect().right>window.innerWidth-12)t.classList.add('flip');})});
"""

CRED_COLORS = {"high": "var(--high)", "medium": "var(--medium)", "low": "var(--low)"}


def _tip(source: Source, n: int, sentence: ReportSentence, sid: int) -> str:
    cred = source.credibility
    evidence = sentence.evidence.get(sid, "")
    if len(evidence) > 420:
        evidence = evidence[:417].rsplit(" ", 1)[0] + "..."
    quote = f"<q>{escape(evidence)}</q>" if evidence else ""
    return (
        f'<span class="tip"><span class="t">[{n}] {escape(source.title)}</span>'
        f'<span class="d">{escape(source.document.domain)}</span>{quote}'
        f'<span class="row"><span>Credibility <span class="badge {cred.label}">{cred.label} '
        f"{cred.score:.2f}</span></span><span>match {sentence.support:.2f}</span></span></span>"
    )


def _sentence(sentence: ReportSentence, report: Report, numbers: dict[int, int]) -> str:
    cites = []
    for n in citation_numbers(sentence.sources, numbers):
        sid = next(k for k, v in numbers.items() if v == n)
        cites.append(
            f'<a class="cite" href="#src-{n}" tabindex="0">{n}{_tip(report.sources[sid], n, sentence, sid)}</a>'
        )
    classes = f"s {sentence.status}" + (" flagged" if sentence.flagged else "")
    title = ""
    if sentence.flagged:
        notes = "; ".join(format_note(x, numbers) for x in sentence.notes) or STATUS_LABELS[sentence.status]
        title = f' title="{escape(STATUS_LABELS[sentence.status] + ": " + notes)}"'
    return f'<span class="{classes}"{title}>{escape(sentence.text)}</span>{"".join(cites)}'


def render_html(report: Report) -> str:
    numbers = number_sources(report)
    sentences = report.all_sentences()
    counts = verification_summary(report)
    supported = counts.get("supported", 0)
    flagged = [s for s in sentences if s.flagged]
    pct = round(100 * supported / len(sentences)) if sentences else 0

    body: list[str] = []
    for section in report.sections:
        body.append(f"<h2>{escape(section.title)}</h2>")
        if section.bullets:
            items = "".join(f"<li>{_sentence(s, report, numbers)}</li>" for s in section.sentences)
            body.append(f"<ul>{items}</ul>")
        else:
            body.append("<p>" + " ".join(_sentence(s, report, numbers) for s in section.sentences) + "</p>")

    body.append("<h2>Verification</h2>")
    if flagged:
        rows = "".join(
            f"<li>{escape(s.text[:140])}{'...' if len(s.text) > 140 else ''} <b>{STATUS_LABELS[s.status]}</b>: "
            f"{escape('; '.join(format_note(x, numbers) for x in s.notes))}</li>"
            for s in flagged
        )
        body.append(
            f'<div class="flags"><b>{len(flagged)} of {len(sentences)} sentences flagged.</b><ul>{rows}</ul></div>'
        )
    else:
        body.append(
            f'<div class="flags clean">All {len(sentences)} sentences were checked against the text of '
            "the sources they cite. None were flagged. Hover any citation to see the passage that backs it.</div>"
        )

    foot = [
        '<div class="foot"><h2>Method</h2>',
        f"<p>Question type: {escape(report.plan.question_type)}. Search queries:</p><ul>",
    ]
    foot += [f"<li>{escape(sq.facet)}: <code>{escape(sq.query)}</code></li>" for sq in report.plan.subqueries]
    foot.append("</ul>")
    if report.exclusions:
        foot.append("<h2>Excluded sources</h2><ul>")
        foot += [f"<li><code>{escape(x.url)}</code>: {escape(x.reason)}</li>" for x in report.exclusions]
        foot.append("</ul>")
    foot.append("</div>")

    panel = ['<div class="panel"><h3>Sources</h3>']
    for sid, n in sorted(numbers.items(), key=lambda kv: kv[1]):
        source = report.sources[sid]
        cred = source.credibility
        panel.append(
            f'<div class="src" id="src-{n}"><span class="n">{n}</span>'
            f'<a href="{escape(source.url)}">{escape(source.title)}</a>'
            f'<div class="dom">{escape(source.document.domain)}'
            f"{' · ' + escape(source.document.author) if source.document.author else ''}</div>"
            f'<span class="badge {cred.label}">{cred.label} {cred.score:.2f}</span>'
            f'<div class="bar"><i style="width:{int(cred.score * 100)}%;background:{CRED_COLORS[cred.label]}"></i></div>'
            f'<div class="why">{escape(", ".join(cred.reasons))}</div></div>'
        )
    extra = uncited_sources(report, numbers)
    if extra:
        panel.append('<h3 style="margin-top:20px">Read, not cited</h3>')
        for sid in extra:
            source = report.sources[sid]
            panel.append(f'<div class="why">{escape(source.title)} ({source.credibility.label})</div>')
    panel.append("</div>")

    chips = [
        f'<span class="chip">Mode <b>{escape(report.mode)}</b></span>',
        f'<span class="chip"><b>{len(numbers)}</b> sources cited</span>',
        f'<span class="chip"><b>{len(report.exclusions)}</b> excluded</span>',
        f'<span class="chip">Verified <b>{supported}/{len(sentences)}</b>'
        f'<span class="meter"><i style="width:{pct}%"></i></span></span>',
    ]
    if report.generated:
        chips.insert(1, f'<span class="chip">{escape(report.generated)}</span>')

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(report.question)}</title><style>{CSS}</style></head>
<body><div class="wrap">
<header><div class="eyebrow">Research report</div><h1>{escape(report.question)}</h1>
<div class="chips">{"".join(chips)}</div></header>
<main><label class="toggle"><input type="checkbox" id="vt"> Highlight verified sentences</label>
{"".join(body)}{"".join(foot)}</main>
<aside>{"".join(panel)}</aside>
</div><script>{JS}</script></body></html>
"""

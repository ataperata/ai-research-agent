"""Readability style main-text extraction using only the standard library.

The approach follows the classic Readability heuristic: build a small DOM, drop obvious
chrome (navigation, footers, cookie banners, sidebars), score each block of prose by
length and comma count, push those scores up to parent containers, then keep the
paragraphs inside the best scoring container after a link-density penalty.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit

from ..models import Document

VOID_TAGS = frozenset(
    [
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    ]
)
DROP_TAGS = frozenset(
    [
        "script",
        "style",
        "noscript",
        "nav",
        "footer",
        "header",
        "aside",
        "form",
        "iframe",
        "svg",
        "button",
        "select",
        "template",
    ]
)
BLOCK_TAGS = frozenset(
    ["p", "li", "blockquote", "pre", "h1", "h2", "h3", "h4", "h5", "h6", "td", "dd", "figcaption"]
)
HEADING_TAGS = frozenset(["h1", "h2", "h3", "h4", "h5", "h6"])
UNLIKELY = re.compile(
    r"comment|cookie|consent|banner|sidebar|share|social|promo|related|footer|nav|menu|"
    r"subscribe|newsletter|advert|\bad-|sponsor|popup|modal|breadcrumb|masthead|widget|"
    r"references|bibliograph|footnote",
    re.I,
)
LIKELY = re.compile(r"article|content|main|post|body|entry|text|story|report", re.I)
REFERENCE_HEADING = re.compile(r"^\s*(references|sources|bibliography|citations|notes)\b", re.I)
DATE_META = ("article:published_time", "datePublished", "date", "dc.date", "pubdate")


@dataclass
class Node:
    tag: str
    attrs: dict[str, str]
    parent: Node | None = None
    children: list[Node | str] = field(default_factory=list)

    def text(self) -> str:
        parts: list[str] = []
        for child in self.children:
            parts.append(child if isinstance(child, str) else child.text())
        return re.sub(r"\s+", " ", " ".join(parts)).strip()

    def link_text_length(self) -> int:
        total = 0
        for child in self.children:
            if isinstance(child, Node):
                total += len(child.text()) if child.tag == "a" else child.link_text_length()
        return total

    def iter(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.iter()


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("document", {})
        self.current = self.root

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k: (v or "") for k, v in attrs}
        # A new block closes an open <p>, the way browsers do it.
        if self.current.tag == "p" and (tag in ("p", "div", "ul", "ol", "table") or tag in HEADING_TAGS):
            self.current = self.current.parent or self.root
        node = Node(tag, attr_map, parent=self.current)
        self.current.children.append(node)
        if tag not in VOID_TAGS:
            self.current = node

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.current.children.append(Node(tag, {k: (v or "") for k, v in attrs}, parent=self.current))

    def handle_endtag(self, tag: str) -> None:
        node: Node | None = self.current
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.current = node.parent

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.current.children.append(data)


def _class_weight(node: Node) -> int:
    label = f"{node.attrs.get('class', '')} {node.attrs.get('id', '')}"
    weight = 0
    if UNLIKELY.search(label):
        weight -= 25
    if LIKELY.search(label):
        weight += 25
    return weight


def _prune(node: Node) -> None:
    kept: list[Node | str] = []
    for child in node.children:
        if isinstance(child, Node):
            label = f"{child.attrs.get('class', '')} {child.attrs.get('id', '')}"
            role = child.attrs.get("role", "")
            if child.tag in DROP_TAGS or role in ("navigation", "banner", "contentinfo"):
                continue
            if UNLIKELY.search(label) and not LIKELY.search(label) and child.tag not in ("body", "article"):
                continue
            _prune(child)
        kept.append(child)
    node.children = kept


def _metadata(root: Node) -> dict[str, str | None]:
    meta: dict[str, str | None] = {"title": None, "author": None, "published": None}
    for node in root.iter():
        if node.tag == "title" and not meta["title"]:
            meta["title"] = node.text() or None
        elif node.tag == "meta":
            key = node.attrs.get("property") or node.attrs.get("name") or node.attrs.get("itemprop") or ""
            content = node.attrs.get("content", "").strip()
            if not content:
                continue
            if key == "og:title":
                meta["title"] = content
            elif key in ("author", "article:author") and not meta["author"]:
                meta["author"] = content
            elif key in DATE_META and not meta["published"]:
                meta["published"] = content
        elif node.tag == "time" and not meta["published"] and node.attrs.get("datetime"):
            meta["published"] = node.attrs["datetime"]
        elif not meta["author"] and (
            node.attrs.get("rel") == "author" or "byline" in node.attrs.get("class", "")
        ):
            text = re.sub(r"^\s*by\s+", "", node.text(), flags=re.I).strip()
            meta["author"] = text or None
    if meta["title"]:
        meta["title"] = re.split("\\s+[|\u2013\u2014-]\\s+", meta["title"])[0].strip()
    return meta


def _count_outbound(root: Node, own_host: str) -> int:
    count = 0
    for node in root.iter():
        if node.tag == "a":
            host = urlsplit(node.attrs.get("href", "")).hostname
            if host and host != own_host:
                count += 1
    return count


def extract(html: str, url: str) -> Document:
    """Extract title, byline, date and the main body paragraphs from an HTML page."""
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    root = builder.root
    meta = _metadata(root)
    own_host = urlsplit(url).hostname or ""
    outbound = _count_outbound(root, own_host)
    has_refs = any(
        node.tag in HEADING_TAGS
        and re.search(r"references|sources|bibliography|citations", node.text(), re.I)
        for node in root.iter()
    ) or bool(re.search(r"\bdoi\.org/|\bdoi:\s*10\.", html, re.I))

    _prune(root)

    scores: dict[int, float] = {}
    nodes: dict[int, Node] = {}
    for node in root.iter():
        if node.tag not in BLOCK_TAGS or node.tag in HEADING_TAGS:
            continue
        text = node.text()
        if len(text) < 25:
            continue
        score = 1 + text.count(",") + min(len(text) / 100, 3)
        parent = node.parent
        for depth, ancestor in enumerate((parent, parent.parent if parent else None)):
            if ancestor is None or ancestor.tag == "document":
                continue
            key = id(ancestor)
            if key not in scores:
                scores[key] = float(_class_weight(ancestor)) + (10 if ancestor.tag == "article" else 0)
                nodes[key] = ancestor
            scores[key] += score if depth == 0 else score / 2

    best: Node | None = None
    best_score = float("-inf")
    for key, raw in scores.items():
        node = nodes[key]
        text_len = len(node.text()) or 1
        adjusted = raw * (1 - node.link_text_length() / text_len)
        if adjusted > best_score:
            best, best_score = node, adjusted
    container = best or root

    paragraphs: list[str] = []
    for node in container.iter():
        if node.tag in BLOCK_TAGS:
            text = unescape(node.text())
            if node.tag in HEADING_TAGS:
                # Reference lists are citations of other work, not claims made by this page.
                if REFERENCE_HEADING.search(text):
                    break
                continue
            if len(text) >= 25 and (node.link_text_length() / max(len(text), 1)) < 0.5:
                paragraphs.append(text)
    # Drop exact duplicates (nested li > p) while keeping order.
    seen: set[str] = set()
    unique = [p for p in paragraphs if not (p in seen or seen.add(p))]

    title = meta["title"]
    if not title:
        h1 = next((n for n in root.iter() if n.tag == "h1"), None)
        title = h1.text() if h1 else own_host
    return Document(
        url=url,
        title=title or own_host,
        paragraphs=unique,
        author=meta["author"],
        published=meta["published"],
        outbound_links=outbound,
        has_references=has_refs,
    )

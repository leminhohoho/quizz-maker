"""Markdown with protected $...$ math (rendered client-side by KaTeX)."""

import re

from markdown_it import MarkdownIt
from markupsafe import Markup, escape

MATH = re.compile(r"\$\$.+?\$\$|\$[^$\n]+?\$", re.S)
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_-]+)\s*\}\}")
_md = MarkdownIt("commonmark", {"html": False}).enable("table")


def _protect(text: str) -> tuple[str, list[str]]:
    spans: list[str] = []

    def stash(m):
        spans.append(m.group(0))
        return f"QZMATH{len(spans) - 1}QZ"

    return MATH.sub(stash, text), spans


def _restore(html: str, spans: list[str]) -> str:
    return re.sub(r"QZMATH(\d+)QZ", lambda m: str(escape(spans[int(m.group(1))])), html)


def markdown(text: str, asset_base: str, *, inline: bool = False) -> Markup:
    protected, spans = _protect(text)
    html = _md.renderInline(protected) if inline else _md.render(protected)
    html = html.replace('src="assets/', f'src="{asset_base}/assets/')
    return Markup(_restore(html, spans))


def fill_prompt(text: str, asset_base: str) -> Markup:
    html = str(markdown(text, asset_base))
    return Markup(
        PLACEHOLDER.sub(
            lambda m: (
                f'<input class="blank" data-blank="{escape(m.group(1))}" form="composer" '
                f'autocomplete="off" spellcheck="false" aria-label="blank {escape(m.group(1))}">'
            ),
            html,
        )
    )


def plain(text: str, limit: int = 90) -> str:
    """Prompt snippet for lists: markdown and placeholders stripped."""
    text = PLACEHOLDER.sub("___", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"[*_`#>]", "", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def fmt_score(value) -> str:
    value = float(value or 0)
    return str(int(value)) if value.is_integer() else f"{value:g}"

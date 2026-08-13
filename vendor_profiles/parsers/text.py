from __future__ import annotations

import html
import re
from datetime import date, datetime
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

_WHITESPACE_RE = re.compile(r"[ \t]+")
_SOFT_BREAK_RE = re.compile(r"[ \t]*\\\s*$", re.MULTILINE)
_BOLD_RE = re.compile(r"\*\*")
_MEDIA_VARIANT_RE = re.compile(r"~(?:rs_|sc_|cr_)[^?\s]*")
_MONEY_RE = re.compile(
    r"\$\s*([\d,]+(?:\.\d+)?)\s*(?:per\s+|/)?\s*(\w+)?",
    re.IGNORECASE,
)
_PER_ALIASES = {
    "hr": "hour",
    "hrs": "hour",
    "hour": "hour",
    "hours": "hour",
    "event": "event",
    "day": "day",
    "days": "day",
    "person": "person",
    "guest": "person",
    "guests": "person",
}
_ALLOWED_PER = frozenset({"hour", "event", "person", "day"})
_DATE_FORMATS = (
    "%B %d, %Y",
    "%b %d, %Y",
    "%B %d %Y",
    "%b %d %Y",
    "%m/%d/%Y",
)


def unescape(text: str) -> str:
    """HTML-unescape, normalize nbsp/whitespace, strip markdown noise."""
    if not text:
        return ""
    out = html.unescape(text)
    out = out.replace("\xa0", " ").replace("\u200b", "")
    out = _SOFT_BREAK_RE.sub("", out)
    out = _BOLD_RE.sub("", out)
    out = _WHITESPACE_RE.sub(" ", out)
    return out.strip()


def clean_or_none(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned = unescape(text)
    return cleaned or None


def absolute_url(url: str) -> str | None:
    """Make protocol-relative URLs absolute; drop data: and empty URLs."""
    raw = (url or "").strip()
    if not raw or raw.startswith("data:"):
        return None
    if raw.startswith("//"):
        return f"https:{raw}"
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return None


def strip_media_variant(url: str) -> str:
    """Drop The Bash / XOGRP image transform suffixes (~rs_..., ~sc_..., ~cr_...)."""
    return _MEDIA_VARIANT_RE.sub("", url)


_TRACKING_PARAMS = frozenset({"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref"})


def strip_tracking_params(url: str) -> str:
    """Drop utm_* / ref query params from an absolute URL."""
    parsed = urlparse(url)
    if not parsed.query:
        return url
    qs = parse_qs(parsed.query, keep_blank_values=True)
    keep = {k: v for k, v in qs.items() if k.lower() not in _TRACKING_PARAMS}
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(keep, doseq=True),
            "",
        )
    ).rstrip("?")


def parse_money(text: str) -> tuple[float, str] | None:
    """Parse '$250 per hour' → (250.0, 'hour')."""
    match = _MONEY_RE.search(text or "")
    if not match:
        return None
    amount_raw = match.group(1).replace(",", "")
    try:
        amount = float(amount_raw)
    except ValueError:
        return None
    unit_raw = (match.group(2) or "event").lower()
    per = _PER_ALIASES.get(unit_raw, unit_raw)
    if per not in _ALLOWED_PER:
        per = "event"
    return amount, per


def parse_date(text: str) -> date | None:
    """Parse 'August 27, 2025' / 'September 18, 2026' → date."""
    cleaned = unescape(text or "")
    if not cleaned:
        return None
    # Strip weekday prefixes like "Fri • "
    cleaned = re.sub(r"^[A-Za-z]{3}\s*[•·]\s*", "", cleaned).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


_MD_ESCAPE_RE = re.compile(r"\\([.\-_*`\[\]()#!])")


def strip_md_escapes(text: str) -> str:
    """Unescape common markdown escapes: \\-, 1\\., \\. → literal chars."""
    if not text:
        return ""
    return _MD_ESCAPE_RE.sub(r"\1", text)


def paragraphs(text: str) -> list[str]:
    """Split text into non-empty paragraphs (blank-line separated), cleaned."""
    if not text:
        return []
    cleaned = strip_md_escapes(unescape(text))
    parts: list[str] = []
    for block in re.split(r"\n\s*\n", cleaned):
        para = re.sub(r"[ \t]*\n[ \t]*", " ", block).strip()
        para = re.sub(r"[ \t]+", " ", para)
        if para:
            parts.append(para)
    return parts


def section(markdown: str, heading: str, *, level: int | None = None) -> str:
    """Slice markdown body between a heading and the next same-or-higher heading.

    ``heading`` is matched case-insensitively against the heading text only
    (without ``#`` markers). Returns "" when the heading is absent.
    """
    if level is None:
        pattern = re.compile(
            rf"^#{{1,4}}\s+{re.escape(heading)}\s*$",
            re.IGNORECASE | re.MULTILINE,
        )
    else:
        pattern = re.compile(
            rf"^#{{{level}}}\s+{re.escape(heading)}\s*$",
            re.IGNORECASE | re.MULTILINE,
        )
    match = pattern.search(markdown)
    if not match:
        return ""

    start = match.end()
    # Determine heading level of the matched line
    hashes = len(match.group(0)) - len(match.group(0).lstrip("#"))
    next_heading = re.compile(
        rf"^#{{1,{hashes}}}\s+\S",
        re.MULTILINE,
    )
    next_match = next_heading.search(markdown, start)
    end = next_match.start() if next_match else len(markdown)
    return markdown[start:end].strip()

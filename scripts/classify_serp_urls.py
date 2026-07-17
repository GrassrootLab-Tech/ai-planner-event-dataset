"""Classify unique SERP organic URLs as single-article vs other.

Reads event_data_serp_results, dedupes by URL, scores with directory/article
regex heuristics, and writes:

  input_urls/single_articles.json
  input_urls/others.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Settings

DEFAULT_OUTPUT_DIR = ROOT / "input_urls"

# ── DIRECTORY / LISTING PATTERNS ──────────────────────────────
DIRECTORY_URL_PATTERNS = [
    # Taxonomy / classification pages
    r"/category/",
    r"/categories/",
    r"/cat/",
    r"/c/",
    r"/tag/",
    r"/tags/",
    r"/tagged/",
    r"/topic/",
    r"/topics/",
    r"/subject/",
    r"/subjects/",
    r"/genre/",
    r"/genres/",
    r"/collection/",
    r"/collections/",
    r"/label/",
    r"/labels/",
    # Archive / date-listing pages (note: different from single-article date URLs)
    r"/archive/",
    r"/archives/",
    r"/\d{4}/?$",  # bare year: /2026/
    r"/\d{4}/\d{2}/?$",  # bare year+month: /2026/07/
    r"/date/\d{4}",
    # Author / contributor pages
    r"/author/",
    r"/authors/",
    r"/contributor/",
    r"/contributors/",
    r"/by/",
    r"/writer/",
    r"/writers/",
    r"/staff/",
    r"/team/",
    r"/profile/",
    r"/profiles/",
    r"/user/",
    r"/users/",
    # Pagination
    r"/page/\d+",
    r"[?&]page=\d+",
    r"[?&][^=&]*_page=\d+",  # Webflow-style: b84ea493_page=18
    r"[?&][^=&]*page=\d+",  # query-0-page=7, etc.
    r"[?&]p=\d+",
    r"/p\d+/?$",
    r"[?&]paged=\d+",
    r"[?&]offset=\d+",
    r"[?&]start=\d+",
    # Search / filter / results pages
    r"/search/?",
    r"[?&]s=",
    r"[?&]q=",
    r"[?&]query=",
    r"/results/?",
    r"/filter/",
    r"[?&]sort=",
    r"[?&]filter",
    # Generic listing / index pages
    r"/index\.html?$",
    r"/sitemap",
    r"/all/?$",
    r"/list/?$",
    r"/browse/?",
    r"/directory/?",
    # Section landing pages (bare, shallow, no article slug)
    r"^/(blog|news|articles?|posts?|stories|press|updates?)/?$",
    r"^/(shop|store|products?|catalog)/?$",
    # Forum / community listing
    r"/forum/",
    r"/forums/",
    r"/board/",
    r"/thread(s)?/?$",
    r"/discussion/",
    r"/community/",
    # E-commerce category/collection (not product detail)
    r"/collections/[^/]+/?$",  # Shopify-style collection root
    r"/c/[^/]+/?$",  # generic category shorthand
    # RSS/feed endpoints (not real content pages)
    r"/feed/?$",
    r"/rss/?$",
    r"\.xml$",
    # Homepage / root
    r"^/$",
]

# ── ARTICLE PATTERNS ───────────────────────────────────────────
ARTICLE_URL_PATTERNS = [
    r"/\d{4}/\d{2}/\d{2}/",  # full date slug: /2026/07/17/
    r"/\d{4}-\d{2}-\d{2}-",  # date-hyphen slug: /2026-07-17-title
    r"/[a-z0-9]+(-[a-z0-9]+){3,}/?$",  # slug with 4+ hyphen-separated words
    r"/p/[a-z0-9-]{10,}",  # medium-style /p/slug
    r"/story/[a-z0-9-]+",
    r"/article[s]?/[a-z0-9-]{8,}",
    r"\.html$",
    r"\.htm$",  # single-page static article endings
    r"/[a-z0-9-]{20,}/?$",  # long single descriptive slug (catch-all)
]

# ── DIRECTORY / LISTING TITLE-DESCRIPTION MARKERS ─────────────
DIRECTORY_TEXT_PATTERNS = [
    # Explicit page-type words
    r"\bcategory\b",
    r"\bcategories\b",
    r"\barchive[s]?\b",
    r"\btag(ged)?\b",
    r"\btags\b",
    r"\btopics?\b",
    r"\bindex\b",
    r"\bsitemap\b",
    r"\bdirectory\b",
    # Aggregation phrasing
    r"\ball (posts|articles|stories|news|results)\b",
    r"\blatest (news|posts|articles|stories|updates)\b",
    r"\bbrowse (all|by)\b",
    r"\bview all\b",
    r"\bmore (articles|posts|stories|news)\b",
    r"\brecent (posts|articles|news)\b",
    r"\btop \d+\b",  # "Top 10 ..." often a listicle/hub, review manually
    r"\bcollection of\b",
    r"\broundup\b",
    # Pagination language
    r"\bpage \d+\b",
    r"\bpage \d+ of \d+\b",
    r"\bnext page\b",
    r"\bprevious page\b",
    # Author/profile hub language
    r"\bposts by\b",
    r"\barticles by\b",
    r"\bauthor:?\s",
    r"\bwritten by\b.*\bprofile\b",
    r"\ball (posts|articles) from\b",
    # Search / filter language
    r"\bsearch results\b",
    r"\bresults for\b",
    r"\byou searched\b",
    r"\bfiltered by\b",
    r"\bsorted by\b",
    # Store/category language
    r"\bshop (all|by)\b",
    r"\bproducts?\s*\(\d+\)",
    r"\b\d+\s*(items|products|results)\s*found\b",
    # Forum/thread listing language
    r"\bforum\b",
    r"\bthread(s)?\b",
    r"\bdiscussion(s)?\b",
    r"\breplies\b",
    # Generic "hub" wording
    r"\beverything (about|on|you need to know)\b",  # borderline, often hub pages
    r"\bguide to\b.*\btopics?\b",
]

# ── ARTICLE TEXT MARKERS (positive signal, not just absence of directory) ──
ARTICLE_TEXT_PATTERNS = [
    r"\b(by|written by)\s+[A-Z][a-z]+\s+[A-Z][a-z]+\b",  # byline: "By John Smith"
    r"\b\d{1,2}\s+(min|minute)\s+read\b",  # "5 min read"
    r"\bpublished (on|in)?\s*[A-Z][a-z]+ \d{1,2}\b",  # "Published on July 17"
    r"\bupdated (on)?\s*[A-Z][a-z]+ \d{1,2}\b",
    r"[.!?]\s+[A-Z]",  # multiple full sentences (real prose)
]


def normalize_url(url: str) -> str:
    return url.strip().rstrip("/")


def score_directory_signals(url: str, title: str, description: str) -> int:
    """Returns a weighted score; higher = more likely directory."""
    score = 0
    path = urlparse(url).path.lower()
    # Query-string directory signals (pagination/search) need the full URL lowercased.
    url_lower = url.lower()
    text_lower = f"{title} {description}".lower()
    text_original = f"{title} {description}"

    for pattern in DIRECTORY_URL_PATTERNS:
        # Patterns with [?&] target query strings; others target path.
        haystack = url_lower if pattern.startswith(r"[?&]") else path
        if re.search(pattern, haystack):
            score += 2  # URL structure is a stronger signal than text

    for pattern in DIRECTORY_TEXT_PATTERNS:
        if re.search(pattern, text_lower):
            score += 1

    for pattern in ARTICLE_URL_PATTERNS:
        if re.search(pattern, path):
            score -= 2

    # Article text patterns use [A-Z] markers — match against original casing.
    for pattern in ARTICLE_TEXT_PATTERNS:
        if re.search(pattern, text_original):
            score -= 1

    # Description length heuristic: real article excerpts tend to be
    # full sentences (100+ chars); directory meta descriptions are often
    # short/generic or templated
    if description and len(description) < 40:
        score += 1
    if description and len(description) > 120 and "." in description:
        score -= 1

    return score


def classify(url: str, title: str, description: str) -> str:
    s = score_directory_signals(url, title, description)
    if s >= 2:
        return "directory"
    if s <= -2:
        return "article"
    return "review"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Classify unique SERP URLs as single-article vs other "
            "and write input_urls JSON files."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args()


def collect_unique_urls(collection: Any) -> dict[str, dict[str, str]]:
    """Return normalized_url -> {url, page_title, description}, first wins."""
    unique: dict[str, dict[str, str]] = {}
    cursor = collection.find(
        {"status": "ok", "results.0": {"$exists": True}},
        {"results": 1},
    )
    for doc in cursor:
        for item in doc.get("results") or []:
            raw_url = item.get("url") or ""
            if not isinstance(raw_url, str) or not raw_url.strip():
                continue
            key = normalize_url(raw_url)
            if not key or key in unique:
                continue
            unique[key] = {
                "url": key,
                "page_title": item.get("title") or "",
                "description": item.get("description") or "",
            }
    return unique


def main() -> None:
    args = parse_args()
    settings = Settings()
    client = MongoClient(settings.mongo_uri)
    collection = client[settings.mongo_db_name][
        settings.event_data_serp_results_collection
    ]

    try:
        unique = collect_unique_urls(collection)
    finally:
        client.close()

    single_articles: list[dict[str, str]] = []
    others: list[dict[str, str]] = []

    for item in unique.values():
        label = classify(item["url"], item["page_title"], item["description"])
        if label == "article":
            single_articles.append(item)
        else:
            others.append(item)

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    articles_path = output_dir / "single_articles.json"
    others_path = output_dir / "others.json"

    articles_path.write_text(
        json.dumps(single_articles, indent=2) + "\n", encoding="utf-8"
    )
    others_path.write_text(json.dumps(others, indent=2) + "\n", encoding="utf-8")

    print(f"Unique URLs: {len(unique)}")
    print(f"single_articles: {len(single_articles)} -> {articles_path}")
    print(f"others: {len(others)} -> {others_path}")


if __name__ == "__main__":
    main()

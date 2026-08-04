from __future__ import annotations

import re
from dataclasses import dataclass

from clients.hasdata_client import HasDataClient
from utils.logger import logger
from vendor_profiles.db.profiles_repo import VendorsScrapedProfilesRepository

# CDN / WAF blocks (e.g. The Knot, WeddingWire via Akamai) often return this shape.
ACCESS_DENIED_RE = re.compile(
    r"(?is)"
    r"(?:^|\n)\s*#\s*access\s+denied\b"
    r"|\baccess\s+denied\b.{0,120}you\s+don'?t\s+have\s+permission\s+to\s+access\b"
    r"|\byou\s+don'?t\s+have\s+permission\s+to\s+access\b.{0,200}\bon\s+this\s+server\b"
    r"|errors\.edgesuite\.net/\S+",
)

ACCESS_DENIED_ERROR = "access_denied"
EMPTY_MARKDOWN_ERROR = "empty_markdown"
MIN_MARKDOWN_LENGTH = 10


@dataclass
class ScrapeOutcome:
    page_url: str
    ok: bool
    detail: str = ""


def looks_like_access_denied(*, html: str, markdown: str) -> bool:
    """True when HasData payload is a block/denial page rather than vendor content."""
    for text in (markdown, html):
        if text and ACCESS_DENIED_RE.search(text):
            return True
    return False


def is_empty_markdown(markdown: str) -> bool:
    return len((markdown or "").strip()) < MIN_MARKDOWN_LENGTH


class VendorScrapeService:
    def __init__(
        self,
        *,
        profiles_repo: VendorsScrapedProfilesRepository,
        hasdata: HasDataClient,
    ) -> None:
        self._profiles = profiles_repo
        self._hasdata = hasdata

    async def scrape_url(self, page_url: str) -> ScrapeOutcome:
        try:
            result = await self._hasdata.scrape(page_url)
            fail_reason: str | None = None
            if looks_like_access_denied(
                html=result.raw_html, markdown=result.markdown
            ):
                fail_reason = ACCESS_DENIED_ERROR
                logger.warning("Access denied content for %s", page_url)
            elif is_empty_markdown(result.markdown):
                fail_reason = EMPTY_MARKDOWN_ERROR
                logger.warning(
                    "Empty/short markdown for %s (len=%d)",
                    page_url,
                    len((result.markdown or "").strip()),
                )

            if fail_reason is not None:
                saved = await self._profiles.save_scrape(
                    page_url,
                    html=result.raw_html,
                    markdown=result.markdown,
                    status="failed",
                    error=fail_reason,
                )
                if not saved:
                    detail = "not updated (status was not staged|failed)"
                    logger.warning("Scrape save skipped for %s: %s", page_url, detail)
                    return ScrapeOutcome(page_url=page_url, ok=False, detail=detail)
                return ScrapeOutcome(page_url=page_url, ok=False, detail=fail_reason)

            saved = await self._profiles.save_scrape(
                page_url,
                html=result.raw_html,
                markdown=result.markdown,
            )
            if not saved:
                detail = "not updated (status was not staged|failed)"
                logger.warning("Scrape save skipped for %s: %s", page_url, detail)
                return ScrapeOutcome(page_url=page_url, ok=False, detail=detail)
            return ScrapeOutcome(page_url=page_url, ok=True)
        except Exception as exc:
            error = str(exc)
            logger.exception("Scrape failed for %s", page_url)
            await self._profiles.mark_failed(page_url, error)
            return ScrapeOutcome(page_url=page_url, ok=False, detail=error)

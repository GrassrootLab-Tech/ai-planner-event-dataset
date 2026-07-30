from __future__ import annotations

from dataclasses import dataclass

from clients.hasdata_client import HasDataClient
from utils.logger import logger
from vendor_profiles.db.profiles_repo import VendorsScrapedProfilesRepository


@dataclass
class ScrapeOutcome:
    page_url: str
    ok: bool
    detail: str = ""


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

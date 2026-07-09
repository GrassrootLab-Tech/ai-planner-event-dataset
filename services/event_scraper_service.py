from clients.hasdata_client import HasDataClient
from db.event_scraped_content_repo import EventScrapedContentRepository
from models.event_scraped_content import EventScrapedContent
from utils.logger import log_pretty, logger
from utils.pipeline_status import check_scrape
from utils.url import extract_website, strip_trailing_slash


class EventScraperService:
    def __init__(
        self,
        hasdata: HasDataClient,
        repo: EventScrapedContentRepository,
    ) -> None:
        self._hasdata = hasdata
        self._repo = repo

    async def scrape_and_store(self, page_url: str, *, skip_status_check: bool = False) -> str:
        page_url = strip_trailing_slash(page_url)

        if not skip_status_check:
            existing = await self._repo.get_by_page_url(page_url)
            check_scrape(
                exists=existing is not None,
                status=existing.status if existing else None,
                page_url=page_url,
            )

        website = extract_website(page_url)
        log_pretty("Prepared scrape job", {
            "page_url": page_url,
            "website": website,
        })

        scrape_result = await self._hasdata.scrape(page_url)
        logger.info("Scrape finished, building document")

        doc = EventScrapedContent(
            page_url=page_url,
            website=website,
            raw_html=scrape_result.raw_html,
            markdown=scrape_result.markdown,
        )

        return await self._repo.insert(doc)

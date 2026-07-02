from clients.hasdata_client import HasDataClient
from db.event_scraped_content_repo import EventScrapedContentRepository
from models.event_scraped_content import EventScrapedContent
from utils.logger import log_pretty, logger
from utils.url import extract_website


class EventScraperService:
    def __init__(
        self,
        hasdata: HasDataClient,
        repo: EventScrapedContentRepository,
    ) -> None:
        self._hasdata = hasdata
        self._repo = repo

    async def scrape_and_store(self, page_url: str) -> str:
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

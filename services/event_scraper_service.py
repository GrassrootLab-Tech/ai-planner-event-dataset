from clients.hasdata_client import HasDataClient
from db.event_scraped_content_repo import EventScrapedContentRepository
from models.event_scraped_content import EventScrapedContent
from reddit import RedditClient, is_reddit_post_url, is_reddit_url, to_storage_dict
from utils.logger import log_pretty, logger
from utils.pipeline_cost import HASDATA_CREDITS_PER_SCRAPE
from utils.pipeline_status import check_scrape
from utils.url import extract_website, strip_trailing_slash


class EventScraperService:
    def __init__(
        self,
        hasdata: HasDataClient,
        repo: EventScrapedContentRepository,
        reddit: RedditClient | None = None,
    ) -> None:
        self._hasdata = hasdata
        self._repo = repo
        self._reddit = reddit

    async def scrape_and_store(
        self,
        page_url: str,
        *,
        skip_status_check: bool = False,
    ) -> tuple[str, dict[str, int]]:
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

        doc, hasdata_credits = await self._build_document(page_url, website)
        logger.info("Scrape finished, storing document")
        doc_id = await self._repo.insert(doc)
        return doc_id, {"hasdata_credits": hasdata_credits}

    async def _build_document(
        self,
        page_url: str,
        website: str,
    ) -> tuple[EventScrapedContent, int]:
        if is_reddit_url(page_url):
            if not is_reddit_post_url(page_url):
                raise ValueError(
                    "Reddit URL must be a post link "
                    f"(expected /r/.../comments/{{id}}/...): {page_url}"
                )
            if self._reddit is None:
                raise ValueError(
                    "REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are required for Reddit URLs"
                )
            thread = await self._reddit.fetch_post(page_url)
            return EventScrapedContent(
                page_url=page_url,
                website=website,
                reddit_data=to_storage_dict(thread),
            ), 0

        scrape_result = await self._hasdata.scrape(page_url)
        return EventScrapedContent(
            page_url=page_url,
            website=website,
            raw_html=scrape_result.raw_html,
            markdown=scrape_result.markdown,
        ), HASDATA_CREDITS_PER_SCRAPE

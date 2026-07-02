import argparse
import asyncio
import sys

from clients.hasdata_client import HasDataClient
from config import Settings
from db.event_scraped_content_repo import EventScrapedContentRepository
from db.mongo import Mongo
from services.event_scraper_service import EventScraperService
from utils.logger import log_pretty, logger, setup_logging


async def run(page_url: str) -> str:
    settings = Settings()
    log_pretty("Loaded settings", {
        "mongo_uri": settings.mongo_uri,
        "mongo_db_name": settings.mongo_db_name,
        "collection": settings.event_scraped_content_collection,
        "hasdata_api_key": f"{settings.hasdata_api_key[:6]}...",
    })

    mongo = Mongo(settings.mongo_uri, settings.mongo_db_name)
    await mongo.connect()

    try:
        repo = EventScrapedContentRepository(
            mongo.db[settings.event_scraped_content_collection]
        )
        await repo.ensure_indexes()

        hasdata = HasDataClient(api_key=settings.hasdata_api_key)
        service = EventScraperService(hasdata, repo)

        logger.info("Starting scrape for page_url=%s", page_url)
        return await service.scrape_and_store(page_url)
    finally:
        await mongo.disconnect()


def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser(description="Scrape a page and store in MongoDB")
    parser.add_argument("page_url", help="URL of the page to scrape")
    args = parser.parse_args()

    try:
        doc_id = asyncio.run(run(args.page_url))
        log_pretty("Scrape completed successfully", {"inserted_id": doc_id})
    except Exception as exc:
        logger.exception("Scrape failed")
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

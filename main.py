import argparse
import asyncio
import sys
from pathlib import Path

from clients.hasdata_client import HasDataClient
from config import Settings
from db.event_scraped_chunks_repo import EventScrapedChunksRepository
from db.event_scraped_content_repo import EventScrapedContentRepository
from db.mongo import Mongo
from services.chunking_service import ChunkingService
from services.event_scraper_service import EventScraperService
from utils.logger import log_pretty, logger, setup_logging


def _log_settings(settings: Settings) -> None:
    log_pretty("Loaded settings", {
        "mongo_uri": settings.mongo_uri,
        "mongo_db_name": settings.mongo_db_name,
        "scraped_collection": settings.event_scraped_content_collection,
        "chunks_collection": settings.event_scraped_chunks_collection,
        "chunk_output_dir": settings.chunk_output_dir,
        "hasdata_api_key": f"{settings.hasdata_api_key[:6]}...",
    })


async def run_scrape(page_url: str) -> str:
    settings = Settings()
    _log_settings(settings)

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


async def run_chunk(page_url: str) -> int:
    settings = Settings()
    _log_settings(settings)

    mongo = Mongo(settings.mongo_uri, settings.mongo_db_name)
    await mongo.connect()

    try:
        content_repo = EventScrapedContentRepository(
            mongo.db[settings.event_scraped_content_collection]
        )
        chunks_repo = EventScrapedChunksRepository(
            mongo.db[settings.event_scraped_chunks_collection]
        )
        await content_repo.ensure_indexes()
        await chunks_repo.ensure_indexes()

        service = ChunkingService(
            content_repo,
            chunks_repo,
            Path(settings.chunk_output_dir),
            min_chars=settings.chunk_min_chars,
        )

        logger.info("Starting chunking for page_url=%s", page_url)
        return await service.chunk_and_store(page_url)
    finally:
        await mongo.disconnect()


def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser(description="Scrape event pages and store in MongoDB")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scrape_parser = subparsers.add_parser("scrape", help="Scrape a page and store in MongoDB")
    scrape_parser.add_argument("page_url", help="URL of the page to scrape")

    chunk_parser = subparsers.add_parser("chunk", help="Chunk scraped markdown for a page")
    chunk_parser.add_argument("page_url", help="URL of the page to chunk")

    args = parser.parse_args()

    try:
        if args.command == "scrape":
            doc_id = asyncio.run(run_scrape(args.page_url))
            log_pretty("Scrape completed successfully", {"inserted_id": doc_id})
        elif args.command == "chunk":
            chunk_count = asyncio.run(run_chunk(args.page_url))
            log_pretty("Chunking completed successfully", {"chunk_count": chunk_count})
    except Exception as exc:
        logger.exception("%s failed", args.command)
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

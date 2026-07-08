import argparse
import asyncio
import sys
from pathlib import Path

from clients.anthropic_tagging_client import AnthropicTaggingClient
from clients.hasdata_client import HasDataClient
from clients.openai_classifier_client import OpenAIClassifierClient
from config import Settings
from db.event_scraped_chunks_repo import EventScrapedChunksRepository
from db.event_scraped_content_repo import EventScrapedContentRepository
from db.mongo import Mongo
from services.chunk_classification_service import ChunkClassificationService
from services.chunk_tagging_service import ChunkTaggingService
from services.chunking_service import ChunkingService
from services.event_scraper_service import EventScraperService
from utils.logger import COMMAND_LOG_STAGES, log_pretty, logger, set_log_stage, setup_logging
from utils.pipeline_status import PipelineSkip


def _log_settings(settings: Settings) -> None:
    log_pretty("Loaded settings", {
        "mongo_uri": settings.mongo_uri,
        "mongo_db_name": settings.mongo_db_name,
        "scraped_collection": settings.event_scraped_content_collection,
        "chunks_collection": settings.event_scraped_chunks_collection,
        "chunk_output_dir": settings.chunk_output_dir,
        "classification_model": settings.openai_classification_model,
        "tagging_model": settings.anthropic_tagging_model,
        "hasdata_api_key": f"{settings.hasdata_api_key[:6]}...",
    })


async def run_scrape(page_url: str) -> str:
    set_log_stage(COMMAND_LOG_STAGES["scrape"])
    settings = Settings()
    _log_settings(settings)

    mongo = Mongo(settings.mongo_uri, settings.mongo_db_name)
    await mongo.connect()

    try:
        repo = EventScrapedContentRepository(
            mongo.db[settings.event_scraped_content_collection]
        )

        hasdata = HasDataClient(api_key=settings.hasdata_api_key)
        service = EventScraperService(hasdata, repo)

        logger.info("Starting scrape for page_url=%s", page_url)
        return await service.scrape_and_store(page_url)
    finally:
        await mongo.disconnect()


async def run_chunk(page_url: str) -> int:
    set_log_stage(COMMAND_LOG_STAGES["chunk"])
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


async def run_classify(page_url: str) -> int:
    set_log_stage(COMMAND_LOG_STAGES["classify"])
    settings = Settings()
    _log_settings(settings)

    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required for classification")

    mongo = Mongo(settings.mongo_uri, settings.mongo_db_name)
    await mongo.connect()

    try:
        content_repo = EventScrapedContentRepository(
            mongo.db[settings.event_scraped_content_collection]
        )
        chunks_repo = EventScrapedChunksRepository(
            mongo.db[settings.event_scraped_chunks_collection]
        )

        classifier = OpenAIClassifierClient(
            api_key=settings.openai_api_key,
            model=settings.openai_classification_model,
        )
        service = ChunkClassificationService(
            content_repo,
            chunks_repo,
            classifier,
        )

        logger.info("Starting classification for page_url=%s", page_url)
        return await service.classify_and_store(page_url)
    finally:
        await mongo.disconnect()


async def run_tag(page_url: str) -> int:
    set_log_stage(COMMAND_LOG_STAGES["tag"])
    settings = Settings()
    _log_settings(settings)

    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is required for tagging")

    mongo = Mongo(settings.mongo_uri, settings.mongo_db_name)
    await mongo.connect()

    try:
        content_repo = EventScrapedContentRepository(
            mongo.db[settings.event_scraped_content_collection]
        )
        chunks_repo = EventScrapedChunksRepository(
            mongo.db[settings.event_scraped_chunks_collection]
        )

        tagger = AnthropicTaggingClient(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_tagging_model,
        )
        service = ChunkTaggingService(
            content_repo,
            chunks_repo,
            tagger,
        )

        logger.info("Starting tagging for page_url=%s", page_url)
        return await service.tag_and_store(page_url)
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

    classify_parser = subparsers.add_parser(
        "classify",
        help="Classify chunk usability for a page",
    )
    classify_parser.add_argument("page_url", help="URL of the page to classify")

    tag_parser = subparsers.add_parser(
        "tag",
        help="AI-tag usable chunks for a page",
    )
    tag_parser.add_argument("page_url", help="URL of the page to tag")

    args = parser.parse_args()

    try:
        if args.command == "scrape":
            doc_id = asyncio.run(run_scrape(args.page_url))
            log_pretty("Scrape completed successfully", {"inserted_id": doc_id})
        elif args.command == "chunk":
            chunk_count = asyncio.run(run_chunk(args.page_url))
            log_pretty("Chunking completed successfully", {"chunk_count": chunk_count})
        elif args.command == "classify":
            classified_count = asyncio.run(run_classify(args.page_url))
            log_pretty("Classification completed successfully", {
                "classified_count": classified_count,
            })
        elif args.command == "tag":
            tagged_count = asyncio.run(run_tag(args.page_url))
            log_pretty("Tagging completed successfully", {
                "tagged_count": tagged_count,
            })
    except PipelineSkip as skip:
        set_log_stage(COMMAND_LOG_STAGES.get(args.command, "pipeline"))
        logger.warning("%s", skip.message)
        print(skip.message)
    except Exception as exc:
        set_log_stage(COMMAND_LOG_STAGES.get(args.command, "pipeline"))
        logger.exception("%s failed", COMMAND_LOG_STAGES.get(args.command, args.command))
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

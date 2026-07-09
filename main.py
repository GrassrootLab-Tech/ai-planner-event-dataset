from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clients.anthropic_tagging_client import AnthropicTaggingClient
from clients.hasdata_client import HasDataClient
from clients.openai_classifier_client import OpenAIClassifierClient
from clients.openai_embedding_client import OpenAIEmbeddingClient
from clients.pinecone_client import PineconeClient
from config import Settings
from db.event_scraped_chunks_repo import EventScrapedChunksRepository
from db.event_scraped_content_repo import EventScrapedContentRepository
from db.mongo import Mongo
from services.chunk_classification_service import ChunkClassificationService
from services.chunk_embedding_service import ChunkEmbeddingService
from services.chunk_tagging_service import ChunkTaggingService
from services.chunking_service import ChunkingService
from services.event_scraper_service import EventScraperService
from utils.logger import COMMAND_LOG_STAGES, log_pretty, logger, set_log_stage, setup_logging
from utils.pipeline_status import (
    PIPELINE_STEP_NAMES,
    PipelineSkip,
    skip_message_for_step,
    steps_to_run,
)

BATCH_REPORT_PATH = Path("output/batch_report.txt")


def _log_settings(settings: Settings) -> None:
    log_pretty("Loaded settings", {
        "mongo_uri": settings.mongo_uri,
        "mongo_db_name": settings.mongo_db_name,
        "scraped_collection": settings.event_scraped_content_collection,
        "chunks_collection": settings.event_scraped_chunks_collection,
        "chunk_output_dir": settings.chunk_output_dir,
        "classification_model": settings.openai_classification_model,
        "embedding_model": settings.openai_embedding_model,
        "tagging_model": settings.anthropic_tagging_model,
        "pinecone_index": settings.pinecone_index_name,
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


async def run_embed(page_url: str) -> int:
    set_log_stage(COMMAND_LOG_STAGES["embed"])
    settings = Settings()
    _log_settings(settings)

    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required for embedding")
    if not settings.pinecone_api_key:
        raise ValueError("PINECONE_API_KEY is required for embedding")

    mongo = Mongo(settings.mongo_uri, settings.mongo_db_name)
    await mongo.connect()

    try:
        content_repo = EventScrapedContentRepository(
            mongo.db[settings.event_scraped_content_collection]
        )
        chunks_repo = EventScrapedChunksRepository(
            mongo.db[settings.event_scraped_chunks_collection]
        )

        embedder = OpenAIEmbeddingClient(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
        )
        pinecone = PineconeClient(
            api_key=settings.pinecone_api_key,
            index_name=settings.pinecone_index_name,
        )
        service = ChunkEmbeddingService(
            content_repo,
            chunks_repo,
            embedder,
            pinecone,
        )

        logger.info("Starting embedding for page_url=%s", page_url)
        return await service.embed_and_store(page_url)
    finally:
        await mongo.disconnect()


@dataclass
class PipelineContext:
    settings: Settings
    mongo: Mongo
    content_repo: EventScrapedContentRepository
    chunks_repo: EventScrapedChunksRepository
    scraper: EventScraperService
    chunker: ChunkingService
    classifier_service: ChunkClassificationService
    tagger_service: ChunkTaggingService
    embedding_service: ChunkEmbeddingService

    @classmethod
    async def create(cls) -> PipelineContext:
        settings = Settings()
        _log_settings(settings)

        mongo = Mongo(settings.mongo_uri, settings.mongo_db_name)
        await mongo.connect()

        content_repo = EventScrapedContentRepository(
            mongo.db[settings.event_scraped_content_collection]
        )
        chunks_repo = EventScrapedChunksRepository(
            mongo.db[settings.event_scraped_chunks_collection]
        )

        return cls(
            settings=settings,
            mongo=mongo,
            content_repo=content_repo,
            chunks_repo=chunks_repo,
            scraper=EventScraperService(
                HasDataClient(api_key=settings.hasdata_api_key),
                content_repo,
            ),
            chunker=ChunkingService(
                content_repo,
                chunks_repo,
                Path(settings.chunk_output_dir),
                min_chars=settings.chunk_min_chars,
            ),
            classifier_service=ChunkClassificationService(
                content_repo,
                chunks_repo,
                OpenAIClassifierClient(
                    api_key=settings.openai_api_key or "",
                    model=settings.openai_classification_model,
                ),
            ),
            tagger_service=ChunkTaggingService(
                content_repo,
                chunks_repo,
                AnthropicTaggingClient(
                    api_key=settings.anthropic_api_key or "",
                    model=settings.anthropic_tagging_model,
                ),
            ),
            embedding_service=ChunkEmbeddingService(
                content_repo,
                chunks_repo,
                OpenAIEmbeddingClient(
                    api_key=settings.openai_api_key or "",
                    model=settings.openai_embedding_model,
                ),
                PineconeClient(
                    api_key=settings.pinecone_api_key or "",
                    index_name=settings.pinecone_index_name,
                ),
            ),
        )

    async def close(self) -> None:
        await self.mongo.disconnect()


async def _execute_pipeline_step(
    ctx: PipelineContext,
    step_name: str,
    page_url: str,
) -> Any:
    if step_name == "scrape":
        set_log_stage(COMMAND_LOG_STAGES["scrape"])
        logger.info("Starting scrape for page_url=%s", page_url)
        return await ctx.scraper.scrape_and_store(page_url, skip_status_check=True)

    if step_name == "chunk":
        set_log_stage(COMMAND_LOG_STAGES["chunk"])
        logger.info("Starting chunking for page_url=%s", page_url)
        return await ctx.chunker.chunk_and_store(page_url, skip_status_check=True)

    if step_name == "classify":
        if not ctx.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for classification")
        set_log_stage(COMMAND_LOG_STAGES["classify"])
        logger.info("Starting classification for page_url=%s", page_url)
        return await ctx.classifier_service.classify_and_store(
            page_url,
            skip_status_check=True,
        )

    if step_name == "tag":
        if not ctx.settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for tagging")
        set_log_stage(COMMAND_LOG_STAGES["tag"])
        logger.info("Starting tagging for page_url=%s", page_url)
        return await ctx.tagger_service.tag_and_store(page_url, skip_status_check=True)

    if step_name == "embed":
        if not ctx.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for embedding")
        if not ctx.settings.pinecone_api_key:
            raise ValueError("PINECONE_API_KEY is required for embedding")
        set_log_stage(COMMAND_LOG_STAGES["embed"])
        logger.info("Starting embedding for page_url=%s", page_url)
        return await ctx.embedding_service.embed_and_store(page_url, skip_status_check=True)

    raise ValueError(f"Unknown pipeline step: {step_name}")


def _step_outcome(
    status: str,
    *,
    message: str | None = None,
    result: Any = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "message": message,
        "result": result,
    }


async def run_pipeline_report(
    page_url: str,
    ctx: PipelineContext | None = None,
) -> dict[str, Any]:
    set_log_stage("pipeline")
    logger.info("Running full pipeline for page_url=%s", page_url)

    own_ctx = ctx is None
    if own_ctx:
        ctx = await PipelineContext.create()

    assert ctx is not None

    try:
        doc = await ctx.content_repo.get_by_page_url(page_url)
        exists = doc is not None
        status = doc.status if doc else None
        steps_to_execute = steps_to_run(exists=exists, status=status)

        steps: dict[str, dict[str, Any]] = {}
        for step_name in PIPELINE_STEP_NAMES:
            if step_name not in steps_to_execute:
                message = skip_message_for_step(
                    step_name,
                    exists=exists,
                    status=status,
                    page_url=page_url,
                )
                logger.warning("%s skipped: %s", step_name, message)
                steps[step_name] = _step_outcome("skipped", message=message)

        failed_at: str | None = None
        error: str | None = None
        error_exception: Exception | None = None

        for index, step_name in enumerate(steps_to_execute):
            try:
                result = await _execute_pipeline_step(ctx, step_name, page_url)
                steps[step_name] = _step_outcome("ok", result=result)
            except PipelineSkip as skip:
                failed_at = step_name
                error = skip.message
                error_exception = skip
                steps[step_name] = _step_outcome("failed", message=skip.message)
                for remaining in steps_to_execute[index + 1:]:
                    steps[remaining] = _step_outcome("not_run")
                break
            except Exception as exc:
                failed_at = step_name
                error = str(exc)
                error_exception = exc
                logger.exception("%s failed for page_url=%s", step_name, page_url)
                steps[step_name] = _step_outcome("failed", message=str(exc))
                for remaining in steps_to_execute[index + 1:]:
                    steps[remaining] = _step_outcome("not_run")
                break

        pipeline_status = "completed" if failed_at is None else "failed"
        report = {
            "page_url": page_url,
            "status": pipeline_status,
            "steps": steps,
            "failed_at": failed_at,
            "error": error,
            "error_exception": error_exception,
        }
        if pipeline_status == "completed":
            log_pretty("Pipeline completed", {
                "page_url": page_url,
                "scrape": steps["scrape"]["status"],
                "chunk": steps["chunk"]["status"],
                "classify": steps["classify"]["status"],
                "tag": steps["tag"]["status"],
                "embed": steps["embed"]["status"],
            })
        else:
            logger.error(
                "Pipeline failed for page_url=%s at %s: %s",
                page_url,
                failed_at,
                error,
            )
        return report
    finally:
        if own_ctx:
            await ctx.close()


async def run_all(page_url: str) -> dict[str, Any]:
    report = await run_pipeline_report(page_url)
    if report["status"] == "failed" and report["error_exception"] is not None:
        raise report["error_exception"]
    return report


def _format_step_line(step_name: str, step: dict[str, Any]) -> str:
    line = f"  {step_name}: {step['status']}"
    if step.get("message"):
        line += f" — {step['message']}"
    if step["status"] == "ok" and step.get("result") is not None:
        line += f" (result={step['result']})"
    return line


def format_batch_report(results: list[dict[str, Any]], started_at: str) -> str:
    lines = [
        f"Batch started: {started_at}",
        f"Total URLs: {len(results)}",
        "",
    ]

    for index, report in enumerate(results, start=1):
        lines.append(f"[{index}/{len(results)}] {report['page_url']}")
        for step_name in PIPELINE_STEP_NAMES:
            lines.append(_format_step_line(step_name, report["steps"][step_name]))
        lines.append(f"  RESULT: {report['status']}")
        if report.get("failed_at"):
            lines.append(f"  FAILED AT: {report['failed_at']}")
        if report.get("error"):
            lines.append(f"  ERROR: {report['error']}")
        lines.append("")

    completed = sum(1 for report in results if report["status"] == "completed")
    failed = sum(1 for report in results if report["status"] == "failed")
    lines.append(f"Summary: {completed} completed, {failed} failed, {len(results)} total")
    return "\n".join(lines) + "\n"


def write_batch_report(results: list[dict[str, Any]], started_at: str) -> Path:
    BATCH_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    BATCH_REPORT_PATH.write_text(
        format_batch_report(results, started_at),
        encoding="utf-8",
    )
    return BATCH_REPORT_PATH


async def run_all_sample() -> tuple[list[dict[str, Any]], Path]:
    from sample_website import PAGE_URLS

    page_urls = [url.strip() for url in PAGE_URLS if url and url.strip()]
    if not page_urls:
        raise ValueError("No URLs in sample_website.PAGE_URLS")

    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    results: list[dict[str, Any]] = []

    ctx = await PipelineContext.create()
    try:
        for index, page_url in enumerate(page_urls, start=1):
            logger.info("Processing sample URL %d/%d", index, len(page_urls))
            results.append(await run_pipeline_report(page_url, ctx))
            write_batch_report(results, started_at)
    finally:
        await ctx.close()

    report_path = write_batch_report(results, started_at)
    return results, report_path


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

    embed_parser = subparsers.add_parser(
        "embed",
        help="Embed usable chunks for a page into Pinecone",
    )
    embed_parser.add_argument("page_url", help="URL of the page to embed")

    run_all_parser = subparsers.add_parser(
        "run-all",
        help="Run scrape, chunk, classify, tag, and embed for one page",
    )
    run_all_parser.add_argument("page_url", help="URL of the page to process")

    subparsers.add_parser(
        "run-all-sample",
        help="Run full pipeline for every URL in sample_website.py",
    )

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
        elif args.command == "embed":
            embedded_count = asyncio.run(run_embed(args.page_url))
            log_pretty("Embedding completed successfully", {
                "embedded_count": embedded_count,
            })
        elif args.command == "run-all":
            asyncio.run(run_all(args.page_url))
        elif args.command == "run-all-sample":
            results, report_path = asyncio.run(run_all_sample())
            failed_count = sum(1 for report in results if report["status"] == "failed")
            log_pretty("Sample batch completed", {
                "url_count": len(results),
                "failed_count": failed_count,
                "report_path": str(report_path),
            })
            if failed_count:
                sys.exit(1)
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

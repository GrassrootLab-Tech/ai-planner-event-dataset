from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic

from clients.anthropic_classifier_client import AnthropicClassifierClient
from clients.anthropic_tagging_client import AnthropicTaggingClient
from clients.hasdata_client import HasDataClient
from clients.openai_embedding_client import OpenAIEmbeddingClient
from clients.pinecone_client import PineconeClient
from clients.spacy_anonymization_client import SpacyAnonymizationClient
from config import Settings
from db.event_scraped_chunks_repo import EventScrapedChunksRepository
from db.event_scraped_content_repo import EventScrapedContentRepository
from db.mongo import Mongo
from reddit import RedditClient
from services.chunk_anonymization_service import ChunkAnonymizationService
from services.chunk_classification_service import ChunkClassificationService
from services.chunk_embedding_service import ChunkEmbeddingService
from services.chunk_tagging_service import ChunkTaggingService, TagBatchCollector
from services.chunking_service import ChunkingService
from services.event_scraper_service import EventScraperService
from retrieval import populate_tag_index
from utils.logger import COMMAND_LOG_STAGES, log_pretty, logger, set_log_stage, setup_logging
from utils.pipeline_cost import (
    article_cost_from_steps,
    cost_report_path_for_run,
    write_cost_report,
)
from utils.pipeline_status import (
    PIPELINE_STEP_NAMES,
    PipelineSkip,
    skip_message_for_step,
    steps_to_run,
)
from utils.url import clean_page_url


def _build_reddit_client(settings: Settings) -> RedditClient | None:
    if not settings.reddit_client_id or not settings.reddit_client_secret:
        return None
    return RedditClient(
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        user_agent=settings.reddit_user_agent,
    )

BATCH_REPORT_PATH = Path("output/batch_report.txt")
STAGE_BATCH_REPORT_PATH = Path("output/stage_batch_report.txt")
STAGE_CHOICES = tuple(PIPELINE_STEP_NAMES)


def normalize_pages(
    raw: Any,
    *,
    skip: int = 0,
    limit: int | None = None,
    source: str = "URL list",
) -> list[dict[str, str | None]]:
    """Validate/clean [{url, page_title?}, ...], then apply skip/limit."""
    if not isinstance(raw, list):
        raise ValueError(f"Expected a list of URL objects in {source}")

    pages: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"Entry {index} in {source} must be an object")
        url_raw = entry.get("url")
        if not isinstance(url_raw, str) or not url_raw.strip():
            url_raw = entry.get("page_url")
        if not isinstance(url_raw, str) or not url_raw.strip():
            continue
        page_url = clean_page_url(url_raw.strip())
        if not page_url or page_url in seen:
            continue
        seen.add(page_url)
        title = entry.get("page_title")
        if isinstance(title, str):
            title = title.strip() or None
        else:
            title = None
        pages.append({"url": page_url, "page_title": title})

    if skip < 0:
        raise ValueError("--skip must be >= 0")
    if limit is not None and limit < 1:
        raise ValueError("--limit must be >= 1")

    sliced = pages[skip:]
    if limit is not None:
        sliced = sliced[:limit]
    return sliced


def load_pages_from_json(
    path: Path,
    *,
    skip: int = 0,
    limit: int | None = None,
) -> list[dict[str, str | None]]:
    """Load URL objects from JSON, clean/dedupe them, and apply skip/limit."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return normalize_pages(raw, skip=skip, limit=limit, source=str(path))


def load_batch_pages(
    json_path: Path | None,
    *,
    skip: int = 0,
    limit: int | None = None,
) -> tuple[list[dict[str, str | None]], str]:
    """Load pages from JSON or sample_website.PAGE_URLS when json_path is None."""
    if json_path is None:
        from sample_website import PAGE_URLS

        pages = normalize_pages(
            PAGE_URLS,
            skip=skip,
            limit=limit,
            source="sample_website.PAGE_URLS",
        )
        return pages, "sample_website.py"

    pages = load_pages_from_json(json_path, skip=skip, limit=limit)
    return pages, json_path.name


def _add_skip_limit_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--skip",
        type=int,
        default=0,
        help="Skip the first N URLs after loading/deduping (default: 0)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N URLs after --skip (default: all remaining)",
    )


def _log_settings(settings: Settings) -> None:
    log_pretty("Loaded settings", {
        "mongo_uri": settings.mongo_uri,
        "mongo_db_name": settings.mongo_db_name,
        "scraped_collection": settings.event_scraped_content_collection,
        "chunks_collection": settings.event_scraped_chunks_collection,
        "classification_model": settings.anthropic_classification_model,
        "embedding_model": settings.openai_embedding_model,
        "tagging_model": settings.anthropic_tagging_model,
        "anonymization_model": settings.spacy_anonymization_model,
        "pinecone_index": settings.pinecone_index_name,
        "pinecone_tags_index": settings.pinecone_tags_index_name,
        "hasdata_api_key": f"{settings.hasdata_api_key[:6]}...",
    })


async def run_scrape(page_url: str, *, page_title: str | None = None) -> str:
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
        service = EventScraperService(hasdata, repo, reddit=_build_reddit_client(settings))

        logger.info("Starting scrape for page_url=%s", page_url)
        doc_id, _ = await service.scrape_and_store(page_url, page_title=page_title)
        return doc_id
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
            min_words=settings.chunk_min_words,
        )

        logger.info("Starting chunking for page_url=%s", page_url)
        return await service.chunk_and_store(page_url)
    finally:
        await mongo.disconnect()


async def run_classify(page_url: str) -> int:
    set_log_stage(COMMAND_LOG_STAGES["classify"])
    settings = Settings()
    _log_settings(settings)

    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is required for classification")

    mongo = Mongo(settings.mongo_uri, settings.mongo_db_name)
    await mongo.connect()
    anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)

    try:
        content_repo = EventScrapedContentRepository(
            mongo.db[settings.event_scraped_content_collection]
        )
        chunks_repo = EventScrapedChunksRepository(
            mongo.db[settings.event_scraped_chunks_collection]
        )

        classifier = AnthropicClassifierClient(
            client=anthropic,
            model=settings.anthropic_classification_model,
        )
        service = ChunkClassificationService(
            content_repo,
            chunks_repo,
            classifier,
        )

        logger.info("Starting classification for page_url=%s", page_url)
        classified_count, _ = await service.classify_and_store(page_url)
        return classified_count
    finally:
        await anthropic.close()
        await mongo.disconnect()


async def run_tag(page_url: str, *, cache: bool = False) -> int:
    set_log_stage(COMMAND_LOG_STAGES["tag"])
    settings = Settings()
    _log_settings(settings)

    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is required for tagging")

    mongo = Mongo(settings.mongo_uri, settings.mongo_db_name)
    await mongo.connect()
    anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)

    try:
        content_repo = EventScrapedContentRepository(
            mongo.db[settings.event_scraped_content_collection]
        )
        chunks_repo = EventScrapedChunksRepository(
            mongo.db[settings.event_scraped_chunks_collection]
        )

        tagger = AnthropicTaggingClient(
            client=anthropic,
            model=settings.anthropic_tagging_model,
            cache=cache,
        )
        service = ChunkTaggingService(
            content_repo,
            chunks_repo,
            tagger,
        )

        logger.info("Starting tagging for page_url=%s", page_url)
        tagged_count, _ = await service.tag_and_store(page_url)
        return tagged_count
    finally:
        await anthropic.close()
        await mongo.disconnect()


async def run_anonymize(page_url: str) -> int:
    set_log_stage(COMMAND_LOG_STAGES["anonymize"])
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

        anonymizer = SpacyAnonymizationClient(
            model=settings.spacy_anonymization_model,
        )
        service = ChunkAnonymizationService(
            content_repo,
            chunks_repo,
            anonymizer,
        )

        logger.info("Starting anonymization for page_url=%s", page_url)
        anonymized_count, _ = await service.anonymize_and_store(page_url)
        return anonymized_count
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
        embedded_count, _ = await service.embed_and_store(page_url)
        return embedded_count
    finally:
        await mongo.disconnect()


async def run_populate_tags() -> int:
    settings = Settings()
    _log_settings(settings)

    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required for tag index population")
    if not settings.pinecone_api_key:
        raise ValueError("PINECONE_API_KEY is required for tag index population")

    embedder = OpenAIEmbeddingClient(
        api_key=settings.openai_api_key,
        model=settings.openai_embedding_model,
    )
    tags_pinecone = PineconeClient(
        api_key=settings.pinecone_api_key,
        index_name=settings.pinecone_tags_index_name,
    )

    logger.info("Starting tag index population for index=%s", settings.pinecone_tags_index_name)
    return await populate_tag_index(embedder, tags_pinecone)


@dataclass
class PipelineContext:
    settings: Settings
    mongo: Mongo
    anthropic: AsyncAnthropic
    content_repo: EventScrapedContentRepository
    chunks_repo: EventScrapedChunksRepository
    scraper: EventScraperService
    chunker: ChunkingService
    classifier_service: ChunkClassificationService
    tagger_service: ChunkTaggingService
    anonymizer_service: ChunkAnonymizationService
    embedding_service: ChunkEmbeddingService
    tag_collector: TagBatchCollector | None = None

    @classmethod
    async def create(cls, *, cache: bool = False) -> PipelineContext:
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
        anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key or "")

        return cls(
            settings=settings,
            mongo=mongo,
            anthropic=anthropic,
            content_repo=content_repo,
            chunks_repo=chunks_repo,
            scraper=EventScraperService(
                HasDataClient(api_key=settings.hasdata_api_key),
                content_repo,
                reddit=_build_reddit_client(settings),
            ),
            chunker=ChunkingService(
                content_repo,
                chunks_repo,
                min_words=settings.chunk_min_words,
            ),
            classifier_service=ChunkClassificationService(
                content_repo,
                chunks_repo,
                AnthropicClassifierClient(
                    client=anthropic,
                    model=settings.anthropic_classification_model,
                ),
            ),
            tagger_service=ChunkTaggingService(
                content_repo,
                chunks_repo,
                AnthropicTaggingClient(
                    client=anthropic,
                    model=settings.anthropic_tagging_model,
                    cache=cache,
                ),
            ),
            anonymizer_service=ChunkAnonymizationService(
                content_repo,
                chunks_repo,
                SpacyAnonymizationClient(
                    model=settings.spacy_anonymization_model,
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
        await self.anthropic.close()
        await self.mongo.disconnect()


async def _execute_pipeline_step(
    ctx: PipelineContext,
    step_name: str,
    page_url: str,
    *,
    page_title: str | None = None,
    skip_status_check: bool = True,
) -> tuple[Any, dict[str, Any]]:
    if step_name == "scrape":
        set_log_stage(COMMAND_LOG_STAGES["scrape"])
        logger.info("Starting scrape for page_url=%s", page_url)
        return await ctx.scraper.scrape_and_store(
            page_url,
            page_title=page_title,
            skip_status_check=skip_status_check,
        )

    if step_name == "chunk":
        set_log_stage(COMMAND_LOG_STAGES["chunk"])
        logger.info("Starting chunking for page_url=%s", page_url)
        count = await ctx.chunker.chunk_and_store(
            page_url,
            skip_status_check=skip_status_check,
        )
        return count, {}

    if step_name == "classify":
        if not ctx.settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for classification")
        set_log_stage(COMMAND_LOG_STAGES["classify"])
        logger.info("Starting classification for page_url=%s", page_url)
        return await ctx.classifier_service.classify_and_store(
            page_url,
            skip_status_check=skip_status_check,
        )

    if step_name == "tag":
        if not ctx.settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for tagging")
        set_log_stage(COMMAND_LOG_STAGES["tag"])
        logger.info("Starting tagging for page_url=%s", page_url)
        if ctx.tag_collector is not None:
            prepared = await ctx.tagger_service.prepare_tag_request(
                page_url,
                skip_status_check=skip_status_check,
            )
            if prepared is None:
                return 0, {"claude_usd": 0.0}
            prepared_url, request, usable_count = prepared
            ctx.tag_collector.add(prepared_url, request)
            return usable_count, {"claude_usd": 0.0}
        return await ctx.tagger_service.tag_and_store(
            page_url,
            skip_status_check=skip_status_check,
        )

    if step_name == "anonymize":
        set_log_stage(COMMAND_LOG_STAGES["anonymize"])
        logger.info("Starting anonymization for page_url=%s", page_url)
        return await ctx.anonymizer_service.anonymize_and_store(
            page_url,
            skip_status_check=skip_status_check,
        )

    if step_name == "embed":
        if not ctx.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for embedding")
        if not ctx.settings.pinecone_api_key:
            raise ValueError("PINECONE_API_KEY is required for embedding")
        set_log_stage(COMMAND_LOG_STAGES["embed"])
        logger.info("Starting embedding for page_url=%s", page_url)
        return await ctx.embedding_service.embed_and_store(
            page_url,
            skip_status_check=skip_status_check,
        )

    raise ValueError(f"Unknown pipeline step: {step_name}")


def _step_outcome(
    status: str,
    *,
    message: str | None = None,
    result: Any = None,
    cost: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "message": message,
        "result": result,
        "cost": cost or {},
    }


async def run_pipeline_report(
    page_url: str,
    ctx: PipelineContext | None = None,
    *,
    page_title: str | None = None,
    cache: bool = False,
) -> dict[str, Any]:
    set_log_stage("pipeline")
    logger.info("Running full pipeline for page_url=%s", page_url)

    own_ctx = ctx is None
    if own_ctx:
        ctx = await PipelineContext.create(cache=cache)

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

        if status == "claude_batch_queued" and not steps_to_execute:
            cost = article_cost_from_steps(page_url, steps)
            log_pretty("Pipeline waiting for Claude batch", {
                "page_url": page_url,
                "claude_task_id": doc.claude_task_id if doc else None,
            })
            return {
                "page_url": page_url,
                "status": "claude_batch_queued",
                "steps": steps,
                "failed_at": None,
                "error": None,
                "error_exception": None,
                "cost": cost,
            }

        failed_at: str | None = None
        error: str | None = None
        error_exception: Exception | None = None

        for index, step_name in enumerate(steps_to_execute):
            try:
                result, cost = await _execute_pipeline_step(
                    ctx,
                    step_name,
                    page_url,
                    page_title=page_title,
                )
                steps[step_name] = _step_outcome("ok", result=result, cost=cost)

                if step_name == "tag":
                    current = await ctx.content_repo.get_by_page_url(page_url)
                    waiting_for_batch = (
                        current is not None
                        and current.status == "claude_batch_queued"
                    ) or (
                        ctx.tag_collector is not None
                        and page_url in ctx.tag_collector.page_urls
                    )
                    if waiting_for_batch:
                        wait_msg = "waiting for Claude batch results"
                        for remaining in steps_to_execute[index + 1:]:
                            steps[remaining] = _step_outcome(
                                "skipped",
                                message=wait_msg,
                            )
                        cost = article_cost_from_steps(page_url, steps)
                        log_pretty("Pipeline paused for Claude batch", {
                            "page_url": page_url,
                            "claude_task_id": (
                                current.claude_task_id if current else None
                            ),
                        })
                        return {
                            "page_url": page_url,
                            "status": "claude_batch_queued",
                            "steps": steps,
                            "failed_at": None,
                            "error": None,
                            "error_exception": None,
                            "cost": cost,
                        }
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
        cost = article_cost_from_steps(page_url, steps)
        report = {
            "page_url": page_url,
            "status": pipeline_status,
            "steps": steps,
            "failed_at": failed_at,
            "error": error,
            "error_exception": error_exception,
            "cost": cost,
        }
        if pipeline_status == "completed":
            log_pretty("Pipeline completed", {
                "page_url": page_url,
                "scrape": steps["scrape"]["status"],
                "chunk": steps["chunk"]["status"],
                "classify": steps["classify"]["status"],
                "tag": steps["tag"]["status"],
                "anonymize": steps["anonymize"]["status"],
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


async def run_all(
    page_url: str,
    *,
    page_title: str | None = None,
    cache: bool = False,
) -> dict[str, Any]:
    report = await run_pipeline_report(page_url, page_title=page_title, cache=cache)
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
    queued = sum(1 for report in results if report["status"] == "claude_batch_queued")
    failed = sum(1 for report in results if report["status"] == "failed")
    lines.append(
        f"Summary: {completed} completed, {queued} claude_batch_queued, "
        f"{failed} failed, {len(results)} total"
    )
    return "\n".join(lines) + "\n"


def write_batch_report(results: list[dict[str, Any]], started_at: str) -> Path:
    BATCH_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    BATCH_REPORT_PATH.write_text(
        format_batch_report(results, started_at),
        encoding="utf-8",
    )
    return BATCH_REPORT_PATH


async def run_all_sample(
    json_path: Path | None = None,
    *,
    skip: int = 0,
    limit: int | None = None,
    cache: bool = False,
) -> tuple[list[dict[str, Any]], Path, Path]:
    pages, source_name = load_batch_pages(json_path, skip=skip, limit=limit)
    if not pages:
        raise ValueError(f"No URLs to process in {source_name} (after skip/limit)")

    started_at_dt = datetime.now(timezone.utc)
    started_at = started_at_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    cost_path = cost_report_path_for_run(started_at_dt)
    results: list[dict[str, Any]] = []

    ctx = await PipelineContext.create(cache=cache)
    ctx.tag_collector = TagBatchCollector()
    try:
        for index, entry in enumerate(pages, start=1):
            page_url = str(entry["url"])
            page_title = entry.get("page_title")
            if isinstance(page_title, str):
                page_title = page_title.strip() or None
            else:
                page_title = None
            logger.info(
                "Processing URL %d/%d from %s",
                index,
                len(pages),
                source_name,
            )
            results.append(await run_pipeline_report(
                page_url,
                ctx,
                page_title=page_title,
            ))
            write_batch_report(results, started_at)
            write_cost_report([report["cost"] for report in results], cost_path)

        if ctx.tag_collector:
            batch_id = await ctx.tagger_service.submit_collected_batch(ctx.tag_collector)
            logger.info("Submitted shared tagging batch id=%s", batch_id)
            final_cost_path = cost_report_path_for_run(started_at_dt, batch_id=batch_id)
            write_cost_report([report["cost"] for report in results], final_cost_path)
            if cost_path != final_cost_path and cost_path.exists():
                cost_path.unlink()
            cost_path = final_cost_path
    finally:
        await ctx.close()

    report_path = write_batch_report(results, started_at)
    write_cost_report([report["cost"] for report in results], cost_path)
    return results, report_path, cost_path


def format_stage_batch_report(
    stage: str,
    results: list[dict[str, Any]],
    started_at: str,
) -> str:
    lines = [
        f"Stage batch started: {started_at}",
        f"Stage: {stage}",
        f"Total URLs: {len(results)}",
        "",
    ]
    for index, report in enumerate(results, start=1):
        lines.append(f"[{index}/{len(results)}] {report['page_url']}")
        lines.append(f"  RESULT: {report['status']}")
        if report.get("message"):
            lines.append(f"  MESSAGE: {report['message']}")
        if report.get("result") is not None:
            lines.append(f"  RESULT_VALUE: {report['result']}")
        lines.append("")

    ok = sum(1 for report in results if report["status"] == "ok")
    skipped = sum(1 for report in results if report["status"] == "skipped")
    queued = sum(1 for report in results if report["status"] == "claude_batch_queued")
    failed = sum(1 for report in results if report["status"] == "failed")
    lines.append(
        f"Summary: {ok} ok, {skipped} skipped, {queued} claude_batch_queued, "
        f"{failed} failed, {len(results)} total"
    )
    return "\n".join(lines) + "\n"


def write_stage_batch_report(
    stage: str,
    results: list[dict[str, Any]],
    started_at: str,
) -> Path:
    STAGE_BATCH_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    STAGE_BATCH_REPORT_PATH.write_text(
        format_stage_batch_report(stage, results, started_at),
        encoding="utf-8",
    )
    return STAGE_BATCH_REPORT_PATH


async def run_stage_batch(
    stage: str,
    json_path: Path | None = None,
    *,
    skip: int = 0,
    limit: int | None = None,
    cache: bool = False,
) -> tuple[list[dict[str, Any]], Path]:
    if stage not in STAGE_CHOICES:
        raise ValueError(f"Unknown stage {stage!r}; choose from {STAGE_CHOICES}")

    pages, source_name = load_batch_pages(json_path, skip=skip, limit=limit)
    if not pages:
        raise ValueError(f"No URLs to process in {source_name} (after skip/limit)")

    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    results: list[dict[str, Any]] = []

    ctx = await PipelineContext.create(cache=cache)
    if stage == "tag":
        ctx.tag_collector = TagBatchCollector()
    try:
        for index, entry in enumerate(pages, start=1):
            page_url = str(entry["url"])
            page_title = entry.get("page_title")
            if isinstance(page_title, str):
                page_title = page_title.strip() or None
            else:
                page_title = None

            logger.info(
                "Stage %s URL %d/%d from %s",
                stage,
                index,
                len(pages),
                source_name,
            )
            try:
                result, _cost = await _execute_pipeline_step(
                    ctx,
                    stage,
                    page_url,
                    page_title=page_title,
                    skip_status_check=False,
                )
                status = "ok"
                message = None
                if stage == "tag" and ctx.tag_collector is not None:
                    if page_url in ctx.tag_collector.page_urls:
                        status = "claude_batch_queued"
                        message = "queued for shared Claude batch"
                results.append({
                    "page_url": page_url,
                    "status": status,
                    "message": message,
                    "result": result,
                })
            except PipelineSkip as skip_exc:
                logger.warning("%s skipped for %s: %s", stage, page_url, skip_exc.message)
                results.append({
                    "page_url": page_url,
                    "status": "skipped",
                    "message": skip_exc.message,
                    "result": None,
                })
            except Exception as exc:
                logger.exception("%s failed for page_url=%s", stage, page_url)
                results.append({
                    "page_url": page_url,
                    "status": "failed",
                    "message": str(exc),
                    "result": None,
                })

            write_stage_batch_report(stage, results, started_at)

        if stage == "tag" and ctx.tag_collector and ctx.tag_collector.page_urls:
            batch_id = await ctx.tagger_service.submit_collected_batch(ctx.tag_collector)
            logger.info("Submitted shared tagging batch id=%s", batch_id)
            for report in results:
                if report["status"] == "claude_batch_queued":
                    report["message"] = f"submitted Claude batch id={batch_id}"
    finally:
        await ctx.close()

    report_path = write_stage_batch_report(stage, results, started_at)
    return results, report_path


def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser(description="Scrape event pages and store in MongoDB")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scrape_parser = subparsers.add_parser("scrape", help="Scrape a page and store in MongoDB")
    scrape_parser.add_argument("page_url", help="URL of the page to scrape")
    scrape_parser.add_argument(
        "--page-title",
        default=None,
        help="Optional page title stored with the scrape and used during tagging",
    )

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
    tag_parser.add_argument(
        "--cache",
        action="store_true",
        default=False,
        help="Cache the tagging system prompt (1h TTL)",
    )

    anonymize_parser = subparsers.add_parser(
        "anonymize",
        help="Anonymize named entities in usable chunks for a page",
    )
    anonymize_parser.add_argument("page_url", help="URL of the page to anonymize")

    embed_parser = subparsers.add_parser(
        "embed",
        help="Embed usable chunks for a page into Pinecone",
    )
    embed_parser.add_argument("page_url", help="URL of the page to embed")

    run_all_parser = subparsers.add_parser(
        "run-all",
        help="Run scrape, chunk, classify, tag, anonymize, and embed for one page",
    )
    run_all_parser.add_argument("page_url", help="URL of the page to process")
    run_all_parser.add_argument(
        "--page-title",
        default=None,
        help="Optional page title stored with the scrape and used during tagging",
    )
    run_all_parser.add_argument(
        "--cache",
        action="store_true",
        default=False,
        help="Cache the tagging system prompt (1h TTL)",
    )

    run_all_sample_parser = subparsers.add_parser(
        "run-all-sample",
        help=(
            "Run full pipeline from a JSON file, or sample_website.py "
            "when no file is provided"
        ),
    )
    run_all_sample_parser.add_argument(
        "json_path",
        nargs="?",
        type=Path,
        help=(
            "Optional JSON array of {url, page_title?} objects; "
            "defaults to sample_website.PAGE_URLS"
        ),
    )
    _add_skip_limit_args(run_all_sample_parser)
    run_all_sample_parser.add_argument(
        "--cache",
        action="store_true",
        default=False,
        help="Cache the tagging system prompt (1h TTL)",
    )

    run_stage_batch_parser = subparsers.add_parser(
        "run-stage-batch",
        help=(
            "Run a single pipeline stage from a JSON file, or sample_website.py "
            "when no file is provided"
        ),
    )
    run_stage_batch_parser.add_argument(
        "stage",
        choices=STAGE_CHOICES,
        help="Pipeline stage to run",
    )
    run_stage_batch_parser.add_argument(
        "json_path",
        nargs="?",
        type=Path,
        help=(
            "Optional JSON array of {url, page_title?} objects; "
            "defaults to sample_website.PAGE_URLS"
        ),
    )
    _add_skip_limit_args(run_stage_batch_parser)
    run_stage_batch_parser.add_argument(
        "--cache",
        action="store_true",
        default=False,
        help="Cache the tagging system prompt (1h TTL; tag stage only)",
    )

    subparsers.add_parser(
        "populate-tags",
        help="Embed and upsert all tag values into the Pinecone tags index",
    )

    args = parser.parse_args()
    if hasattr(args, "page_url"):
        args.page_url = clean_page_url(args.page_url.strip())

    try:
        if args.command == "scrape":
            doc_id = asyncio.run(run_scrape(args.page_url, page_title=args.page_title))
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
            tagged_count = asyncio.run(run_tag(args.page_url, cache=args.cache))
            log_pretty("Tagging step finished", {
                "usable_chunk_count": tagged_count,
            })
        elif args.command == "anonymize":
            anonymized_count = asyncio.run(run_anonymize(args.page_url))
            log_pretty("Anonymization completed successfully", {
                "anonymized_count": anonymized_count,
            })
        elif args.command == "embed":
            embedded_count = asyncio.run(run_embed(args.page_url))
            log_pretty("Embedding completed successfully", {
                "embedded_count": embedded_count,
            })
        elif args.command == "run-all":
            asyncio.run(run_all(
                args.page_url,
                page_title=args.page_title,
                cache=args.cache,
            ))
        elif args.command == "run-all-sample":
            results, report_path, cost_path = asyncio.run(
                run_all_sample(
                    args.json_path,
                    skip=args.skip,
                    limit=args.limit,
                    cache=args.cache,
                )
            )
            failed_count = sum(1 for report in results if report["status"] == "failed")
            log_pretty("Sample batch completed", {
                "url_count": len(results),
                "failed_count": failed_count,
                "report_path": str(report_path),
                "cost_path": str(cost_path),
            })
            if failed_count:
                sys.exit(1)
        elif args.command == "run-stage-batch":
            results, report_path = asyncio.run(
                run_stage_batch(
                    args.stage,
                    args.json_path,
                    skip=args.skip,
                    limit=args.limit,
                    cache=args.cache,
                )
            )
            failed_count = sum(1 for report in results if report["status"] == "failed")
            log_pretty("Stage batch completed", {
                "stage": args.stage,
                "url_count": len(results),
                "failed_count": failed_count,
                "report_path": str(report_path),
            })
            if failed_count:
                sys.exit(1)
        elif args.command == "populate-tags":
            vector_count = asyncio.run(run_populate_tags())
            log_pretty("Tag index population completed", {"vector_count": vector_count})
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

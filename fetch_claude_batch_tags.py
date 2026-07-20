from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from datetime import datetime, timezone

from anthropic import AsyncAnthropic

from clients.anthropic_tagging_client import AnthropicTaggingClient, TaggingError
from config import Settings
from db.event_scraped_chunks_repo import EventScrapedChunksRepository
from db.event_scraped_content_repo import EventScrapedContentRepository
from db.mongo import Mongo
from services.chunk_tagging_service import ChunkTaggingService
from utils.concurrency import map_concurrent
from utils.logger import log_pretty, logger, set_log_stage, setup_logging
from utils.pipeline_cost import (
    ArticleCost,
    tagging_cost_report_path_for_run,
    token_usage_message_record,
    token_usage_report_path_for_batch,
    usd_for_model,
    write_tagging_cost_report,
    write_token_usage_report,
)


async def fetch_and_apply_batch_tags(*, concurrency: int = 1) -> tuple[int, int, int]:
    set_log_stage("ai_tagging")
    if concurrency < 1:
        raise ValueError("--concurrency must be >= 1")

    settings = Settings()

    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is required to fetch tagging batches")

    mongo = Mongo(settings.mongo_uri, settings.mongo_db_name)
    await mongo.connect()
    anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)

    applied = 0
    skipped = 0
    errors = 0
    started_at = datetime.now(timezone.utc)

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
        )
        service = ChunkTaggingService(content_repo, chunks_repo, tagger)

        docs = await content_repo.list_by_status("claude_batch_queued")
        logger.info(
            "Found %d docs with status=claude_batch_queued (concurrency=%d)",
            len(docs),
            concurrency,
        )

        by_batch: dict[str, list[tuple[str, object]]] = defaultdict(list)
        for content_id, doc in docs:
            if not doc.claude_task_id:
                logger.error(
                    "Missing claude_task_id for page_url=%s; skipping",
                    doc.page_url,
                )
                errors += 1
                continue
            by_batch[doc.claude_task_id].append((content_id, doc))

        cost_paths: list[str] = []

        for task_id, batch_docs in by_batch.items():
            batch_cost_rows: list[ArticleCost] = []
            batch_token_rows: list[dict] = []
            try:
                batch = await anthropic.messages.batches.retrieve(task_id)
                counts = batch.request_counts
                finished = (
                    counts.succeeded
                    + counts.errored
                    + counts.canceled
                    + counts.expired
                )
                total = finished + counts.processing
                progress_pct = (finished / total * 100) if total else 0.0
                log_pretty("Claude batch progress", {
                    "batch_id": task_id,
                    "status": batch.processing_status,
                    "total": total,
                    "processing": counts.processing,
                    "succeeded": counts.succeeded,
                    "errored": counts.errored,
                    "canceled": counts.canceled,
                    "expired": counts.expired,
                    "progress_pct": round(progress_pct, 1),
                    "created_at": str(batch.created_at),
                    "ended_at": str(batch.ended_at) if batch.ended_at else None,
                })
                if batch.processing_status != "ended":
                    logger.info(
                        "Batch still %s task_id=%s; skipping until ended",
                        batch.processing_status,
                        task_id,
                    )
                    skipped += len(batch_docs)
                    continue

                results_by_custom_id: dict[str, object] = {}
                async for item in await anthropic.messages.batches.results(task_id):
                    result = item.result
                    if getattr(result, "type", None) != "succeeded":
                        logger.error(
                            "Batch result type=%s custom_id=%s task_id=%s",
                            getattr(result, "type", None),
                            item.custom_id,
                            task_id,
                        )
                        errors += 1
                        continue
                    results_by_custom_id[item.custom_id] = result.message

                async def apply_one(
                    content_doc: tuple[str, object],
                ) -> tuple[str, ArticleCost | None, dict | None]:
                    content_id, doc = content_doc
                    page_url = doc.page_url
                    message = results_by_custom_id.get(content_id)
                    if message is None:
                        logger.error(
                            "No succeeded result for content_id=%s page_url=%s "
                            "task_id=%s",
                            content_id,
                            page_url,
                            task_id,
                        )
                        return "error", None, None

                    try:
                        chunks = await chunks_repo.list_by_page_url(page_url)
                        usable_count = sum(
                            1
                            for _, chunk_doc in chunks
                            if chunk_doc.is_usable is not None
                            and chunk_doc.is_usable.value
                        )
                        tag_defs = service.registry.all_tags()
                        results, usage, _raw_output = tagger.parse_message_result(
                            message,
                            tag_defs,
                            usable_count,
                        )
                        await service.apply_tag_results(page_url, results)

                        claude_usd = usd_for_model(tagger.model, usage, batch=True)
                        cost_row = ArticleCost(page_url=page_url, claude_usd=claude_usd)
                        token_row = token_usage_message_record(
                            page_url=page_url,
                            content_id=content_id,
                            usage=usage,
                            claude_usd=claude_usd,
                        )
                        log_pretty("Applied batch tags", {
                            "page_url": page_url,
                            "content_id": content_id,
                            "claude_task_id": task_id,
                            "usable_chunk_count": usable_count,
                            "claude_usd": claude_usd,
                            "input_tokens": usage.input_tokens,
                            "output_tokens": usage.output_tokens,
                            "cache_creation_input_tokens": (
                                usage.cache_creation_input_tokens
                            ),
                            "cache_read_input_tokens": usage.cache_read_input_tokens,
                        })
                        return "applied", cost_row, token_row
                    except TaggingError:
                        logger.exception(
                            "Failed to parse tags for page_url=%s",
                            page_url,
                        )
                        return "error", None, None
                    except Exception:
                        logger.exception(
                            "Failed to apply batch for page_url=%s",
                            page_url,
                        )
                        return "error", None, None

                outcomes = await map_concurrent(batch_docs, concurrency, apply_one)
                for status, cost_row, token_row in outcomes:
                    if status == "applied":
                        applied += 1
                        if cost_row is not None:
                            batch_cost_rows.append(cost_row)
                        if token_row is not None:
                            batch_token_rows.append(token_row)
                    else:
                        errors += 1

                if batch_cost_rows:
                    cost_path = tagging_cost_report_path_for_run(started_at, task_id)
                    write_tagging_cost_report(batch_cost_rows, cost_path)
                    cost_paths.append(str(cost_path))
                if batch_token_rows:
                    token_path = token_usage_report_path_for_batch(task_id)
                    write_token_usage_report(
                        batch_token_rows,
                        token_path,
                        results_url=batch.results_url,
                    )
                    cost_paths.append(str(token_path))
            except Exception:
                logger.exception("Failed to fetch batch task_id=%s", task_id)
                errors += len(batch_docs)

        log_pretty("Claude batch tag fetch finished", {
            "applied": applied,
            "skipped": skipped,
            "errors": errors,
            "cost_paths": cost_paths,
        })
        return applied, skipped, errors
    finally:
        await anthropic.close()
        await mongo.disconnect()


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Fetch ended Claude tagging batches and apply results to Mongo",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Max pages to apply in parallel per batch (default: 1)",
    )
    args = parser.parse_args()
    try:
        applied, skipped, errors = asyncio.run(
            fetch_and_apply_batch_tags(concurrency=args.concurrency)
        )
        log_pretty("Done", {
            "applied": applied,
            "skipped": skipped,
            "errors": errors,
        })
        if errors:
            raise SystemExit(1)
    except SystemExit:
        raise
    except Exception as exc:
        logger.exception("fetch_claude_batch_tags failed")
        print(f"Error: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

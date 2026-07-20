"""List all Claude Message Batch IDs (Anthropic API only, no status filter).

Usage:
  python list_queued_claude_batches.py
"""

from __future__ import annotations

import asyncio

from anthropic import AsyncAnthropic

from config import Settings
from utils.logger import log_pretty, logger, set_log_stage, setup_logging


async def list_claude_batches() -> list[dict]:
    set_log_stage("ai_tagging")
    settings = Settings()
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is required")

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    rows: list[dict] = []
    try:
        async for batch in client.messages.batches.list(limit=100):
            counts = batch.request_counts
            total_requests = (
                counts.processing
                + counts.succeeded
                + counts.errored
                + counts.canceled
                + counts.expired
            )
            row = {
                "batch_id": batch.id,
                "status": getattr(batch, "processing_status", None),
                "created_at": str(batch.created_at),
                "ended_at": str(batch.ended_at) if batch.ended_at else None,
                "total_requests": total_requests,
                "processing": counts.processing,
                "succeeded": counts.succeeded,
                "errored": counts.errored,
                "canceled": counts.canceled,
                "expired": counts.expired,
            }
            rows.append(row)
            log_pretty("Claude batch", row)
    finally:
        await client.close()

    log_pretty("Claude batches summary", {
        "batch_count": len(rows),
        "total_requests": sum(row["total_requests"] for row in rows),
        "batch_ids": [row["batch_id"] for row in rows],
    })
    for row in rows:
        print(
            f"{row['batch_id']}\t{row['status']}\t"
            f"total_requests={row['total_requests']}\t"
            f"processing={row['processing']}\t"
            f"succeeded={row['succeeded']}\t"
            f"errored={row['errored']}\t"
            f"created_at={row['created_at']}"
        )
    return rows


def main() -> None:
    setup_logging()
    try:
        rows = asyncio.run(list_claude_batches())
        if not rows:
            print("No Claude batches found.")
    except Exception as exc:
        logger.exception("list_queued_claude_batches failed")
        print(f"Error: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

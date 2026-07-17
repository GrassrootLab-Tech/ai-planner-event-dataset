"""Fetch Claude Message Batch results for sanity checks (no pipeline side effects).

Usage:
    python fetch_claude_batch_results_independent.py msgbatch_01...
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from anthropic import AsyncAnthropic

from config import Settings

OUTPUT_DIR = Path("output/claude_batch")


async def fetch_batch_results(batch_id: str) -> Path:
    settings = Settings()
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is required")

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        batch = await client.messages.batches.retrieve(batch_id)
        results: list[dict] = []
        if batch.processing_status == "ended":
            async for item in await client.messages.batches.results(batch_id):
                results.append(item.model_dump(mode="json"))

        payload = {
            "batch_id": batch_id,
            "batch": batch.model_dump(mode="json"),
            "results": results,
        }

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUT_DIR / f"claude_batch_results__{batch_id}_independent.json"
        out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return out_path
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Claude batch results to an independent JSON file.",
    )
    parser.add_argument("batch_id", help="Claude Message Batch id (msgbatch_...)")
    args = parser.parse_args()

    try:
        out_path = asyncio.run(fetch_batch_results(args.batch_id.strip()))
        print(f"Wrote {out_path}")
    except Exception as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

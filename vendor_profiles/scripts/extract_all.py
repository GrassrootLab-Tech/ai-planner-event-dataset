"""Extract scraped vendor profiles in DB batches (upsert into extracted).

Loads up to --batch-size (default 100) status=scraped profiles at a time,
extracts them (rules or Haiku), upserts into vendors_extracted_profiles, then
marks scraped → extracted / failed. With --all, repeats until none remain.

Uses a single Mongo connection for the whole run (indexes ensured once).

Usage:
  python -m vendor_profiles.scripts.extract_all --all
  python -m vendor_profiles.scripts.extract_all --all --concurrency 20
  python -m vendor_profiles.scripts.extract_all --batch-size 100 --concurrency 10
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anthropic import AsyncAnthropic  # noqa: E402

from db.mongo import Mongo  # noqa: E402
from utils.concurrency import map_concurrent  # noqa: E402
from utils.logger import logger, set_log_stage, setup_logging  # noqa: E402
from vendor_profiles.clients.anthropic_vendor_extract_client import (  # noqa: E402
    AnthropicVendorExtractClient,
)
from vendor_profiles.config import VendorSettings  # noqa: E402
from vendor_profiles.db.extracted_profiles_repo import (  # noqa: E402
    VendorsExtractedProfilesRepository,
)
from vendor_profiles.db.profiles_repo import VendorsScrapedProfilesRepository  # noqa: E402
from vendor_profiles.services.extract_service import (  # noqa: E402
    ExtractOutcome,
    VendorExtractService,
)

DEFAULT_BATCH_SIZE = 100


async def _extract_batch(
    *,
    service: VendorExtractService,
    profiles_repo: VendorsScrapedProfilesRepository,
    batch_size: int,
    concurrency: int,
    batch_num: int,
) -> list[ExtractOutcome]:
    candidates = await profiles_repo.list_extract_candidates(batch_size)
    if not candidates:
        return []

    pages = [c["page_url"] for c in candidates]
    total = len(pages)
    logger.info(
        "Extract batch %d: %d URLs batch_size=%d concurrency=%d",
        batch_num,
        total,
        batch_size,
        concurrency,
    )

    progress_lock = asyncio.Lock()
    progress_done = 0

    async def extract_one(page_url: str) -> ExtractOutcome:
        nonlocal progress_done
        outcome = await service.extract_url(page_url)
        async with progress_lock:
            progress_done += 1
            done = progress_done
        status = "ok" if outcome.outcome == "extracted" else outcome.outcome
        method = (
            f" method={outcome.extraction_method}"
            if outcome.extraction_method
            else ""
        )
        print(
            f"batch {batch_num} [{done} / {total}] {status}{method} {page_url}"
            + (f" | {outcome.detail}" if outcome.detail else "")
        )
        return outcome

    return await map_concurrent(pages, concurrency, extract_one)


async def run(*, all_batches: bool, batch_size: int, concurrency: int) -> int:
    set_log_stage("vendor_extract")
    settings = VendorSettings()

    extract_client: AnthropicVendorExtractClient | None = None
    if settings.anthropic_api_key:
        extract_client = AnthropicVendorExtractClient(
            AsyncAnthropic(api_key=settings.anthropic_api_key),
            model=settings.anthropic_link_filter_model,
        )
    else:
        logger.warning(
            "ANTHROPIC_API_KEY unset — rule parsers only; "
            "sources without a parser will be skipped"
        )

    mongo = Mongo(settings.mongo_uri, settings.mongo_db_name)
    await mongo.connect()
    try:
        profiles_repo = VendorsScrapedProfilesRepository(
            mongo.db[settings.vendors_scraped_profiles_collection]
        )
        extracted_repo = VendorsExtractedProfilesRepository(
            mongo.db[settings.vendors_extracted_profiles_collection]
        )
        await profiles_repo.ensure_indexes()
        await extracted_repo.ensure_indexes()

        service = VendorExtractService(
            profiles_repo=profiles_repo,
            extracted_repo=extracted_repo,
            extract_client=extract_client,
        )

        batches_done = 0
        totals = {
            "urls": 0,
            "extracted": 0,
            "skipped": 0,
            "failed": 0,
        }

        while True:
            results = await _extract_batch(
                service=service,
                profiles_repo=profiles_repo,
                batch_size=batch_size,
                concurrency=concurrency,
                batch_num=batches_done + 1,
            )
            if not results:
                if batches_done == 0:
                    print("No scraped profiles to extract — nothing to do")
                else:
                    print(
                        f"Done after {batches_done} batch(es); "
                        "no more scraped profiles"
                    )
                break

            batches_done += 1
            extracted = sum(1 for r in results if r.outcome == "extracted")
            skipped = sum(1 for r in results if r.outcome == "skipped")
            failed = sum(1 for r in results if r.outcome == "error")
            totals["urls"] += len(results)
            totals["extracted"] += extracted
            totals["skipped"] += skipped
            totals["failed"] += failed

            print(
                f"batch {batches_done} summary: "
                f"urls={len(results)} extracted={extracted} "
                f"skipped={skipped} failed={failed}"
            )

            if not all_batches:
                break

        print(
            "overall summary: "
            f"batches={batches_done} "
            f"urls={totals['urls']} extracted={totals['extracted']} "
            f"skipped={totals['skipped']} failed={totals['failed']}"
        )
        return totals["failed"]
    finally:
        await mongo.disconnect()


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(
        description=(
            "Extract status=scraped profiles in batches "
            "(default one batch; --all until none left)"
        )
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Keep loading batches until no status=scraped profiles remain",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Profiles to load from DB per batch (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Max URLs to extract in parallel within a batch (default: 3)",
    )
    args = parser.parse_args()

    if args.batch_size < 1:
        parser.error("--batch-size must be >= 1")
    if args.concurrency < 1:
        parser.error("--concurrency must be >= 1")

    failed = asyncio.run(
        run(
            all_batches=args.all,
            batch_size=args.batch_size,
            concurrency=args.concurrency,
        )
    )
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()

"""CLI for vendor profile SERP + stage + scrape + extract pipeline.

  python -m vendor_profiles stage [--batch-size 100] [--concurrency 3]
  python -m vendor_profiles stage --run-sample [--concurrency 3]
  python -m vendor_profiles scrape [--batch-size 100] [--concurrency 3]
  python -m vendor_profiles extract [--batch-size 100] [--concurrency 3]
  python -m vendor_profiles extract --run-sample [--concurrency 3]
  python -m vendor_profiles fetch-serp [--workers 4]
  python -m vendor_profiles poll-serp [--workers 4]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic

from clients.hasdata_client import HasDataClient
from db.mongo import Mongo
from utils.concurrency import map_concurrent
from utils.logger import log_pretty, logger, set_log_stage, setup_logging
from utils.pipeline_cost import TokenUsage, usd_for_model
from utils.url import clean_page_url
from vendor_profiles.clients.anthropic_vendor_extract_client import (
    AnthropicVendorExtractClient,
)
from vendor_profiles.clients.anthropic_vendor_link_client import AnthropicVendorLinkClient
from vendor_profiles.config import VendorSettings
from vendor_profiles.db.directory_urls_repo import VendorsScrapedDirectoryUrlsRepository
from vendor_profiles.db.extracted_profiles_repo import (
    VendorsExtractedProfilesRepository,
)
from vendor_profiles.db.profiles_repo import VendorsScrapedProfilesRepository
from vendor_profiles.db.serp_results_repo import StagePage, VendorsSerpResultsRepository
from vendor_profiles.sample_urls import PAGE_URLS
from vendor_profiles.scripts.fetch_serp import DEFAULT_WORKERS, run_fetch_serp
from vendor_profiles.scripts.poll_serp import run_poll_serp
from vendor_profiles.services.extract_service import ExtractOutcome, VendorExtractService
from vendor_profiles.services.scrape_service import ScrapeOutcome, VendorScrapeService
from vendor_profiles.services.stage_service import (
    VENDOR_OUTPUT_DIR,
    VENDOR_STAGE_REPORT_PATH,
    StageResult,
    VendorStageService,
)

OUTPUT_DIR = VENDOR_OUTPUT_DIR
DEFAULT_BATCH_SIZE = 100


def _log_settings(settings: VendorSettings) -> None:
    log_pretty(
        "Loaded vendor settings",
        {
            "mongo_uri": settings.mongo_uri,
            "mongo_db_name": settings.mongo_db_name,
            "vendor_data_serp_results_collection": (
                settings.vendor_data_serp_results_collection
            ),
            "vendors_scraped_profiles_collection": (
                settings.vendors_scraped_profiles_collection
            ),
            "vendors_scraped_directory_urls_collection": (
                settings.vendors_scraped_directory_urls_collection
            ),
            "vendors_extracted_profiles_collection": (
                settings.vendors_extracted_profiles_collection
            ),
            "anthropic_link_filter_model": settings.anthropic_link_filter_model,
            "hasdata_api_key": f"{settings.hasdata_api_key[:6]}...",
            "dataforseo_login_set": bool(settings.dataforseo_login),
            "anthropic_api_key_set": bool(settings.anthropic_api_key),
        },
    )


def normalize_pages(
    raw: Any,
    *,
    source: str = "URL list",
) -> list[StagePage]:
    if not isinstance(raw, list):
        raise ValueError(f"Expected a list of URL objects in {source}")

    pages: list[StagePage] = []
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
        pages.append(StagePage(page_url=page_url, page_title=title))
    return pages


def _write_stage_run_report(
    results: list[StageResult],
    *,
    model: str,
    started_at: datetime,
) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = started_at.strftime("%Y%m%d_%H%M%S")
    path = OUTPUT_DIR / f"{stamp}_{len(results)}_urls_run.txt"

    lines: list[str] = [
        f"vendor_profiles stage run — {started_at.isoformat()}",
        f"model: {model}",
        f"urls: {len(results)}",
        "",
        "per_url:",
    ]

    total_usage = TokenUsage()
    success = 0
    failed = 0
    for result in results:
        status = "success" if result.ok else "failed"
        if result.ok:
            success += 1
        else:
            failed += 1
        cost = usd_for_model(model, result.haiku_usage)
        total_usage = total_usage + result.haiku_usage
        lines.append(
            f"  [{status}] {result.page_url} | outcome={result.outcome}"
            f" | profiles_inserted={result.profiles_inserted}"
            f" | haiku_input={result.haiku_usage.input_tokens}"
            f" | haiku_output={result.haiku_usage.output_tokens}"
            f" | haiku_cost_usd={cost:.6f}"
            + (f" | detail={result.detail}" if result.detail else "")
        )

    total_cost = usd_for_model(model, total_usage)
    lines.extend(
        [
            "",
            "summary:",
            f"  total_urls: {len(results)}",
            f"  success: {success}",
            f"  failed: {failed}",
            f"  haiku_input_tokens: {total_usage.input_tokens}",
            f"  haiku_output_tokens: {total_usage.output_tokens}",
            f"  total_haiku_cost_usd: {total_cost:.6f}",
        ]
    )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


async def run_stage(
    *,
    concurrency: int = 3,
    run_sample: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[StageResult]:
    set_log_stage("vendor_stage")
    if concurrency < 1:
        raise ValueError("--concurrency must be >= 1")
    if not run_sample and batch_size < 1:
        raise ValueError("--batch-size must be >= 1")

    settings = VendorSettings()
    _log_settings(settings)

    started_at = datetime.now(timezone.utc)
    VENDOR_STAGE_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    VENDOR_STAGE_REPORT_PATH.write_text("", encoding="utf-8")

    mongo = Mongo(settings.mongo_uri, settings.mongo_db_name)
    await mongo.connect()
    try:
        profiles_repo = VendorsScrapedProfilesRepository(
            mongo.db[settings.vendors_scraped_profiles_collection]
        )
        directory_repo = VendorsScrapedDirectoryUrlsRepository(
            mongo.db[settings.vendors_scraped_directory_urls_collection]
        )
        serp_repo = VendorsSerpResultsRepository(
            mongo.db[settings.vendor_data_serp_results_collection]
        )
        await profiles_repo.ensure_indexes()
        await directory_repo.ensure_indexes()

        if run_sample:
            pages = normalize_pages(
                PAGE_URLS, source="vendor_profiles.sample_urls.PAGE_URLS"
            )
            if not pages:
                logger.warning("sample_urls.PAGE_URLS is empty — nothing to stage")
                return []
            logger.info(
                "Vendor stage (sample): %d URLs (concurrency=%d)",
                len(pages),
                concurrency,
            )
        else:
            pages = await serp_repo.pick_unprocessed_batch(batch_size)
            if not pages:
                logger.warning(
                    "No unprocessed SERP result URLs — nothing to stage"
                )
                print("No unprocessed SERP result URLs — nothing to stage")
                return []
            logger.info(
                "Vendor stage (serp): %d URLs batch_size=%d concurrency=%d",
                len(pages),
                batch_size,
                concurrency,
            )

        link_client = (
            AnthropicVendorLinkClient(
                AsyncAnthropic(api_key=settings.anthropic_api_key),
                model=settings.anthropic_link_filter_model,
            )
            if settings.anthropic_api_key
            else None
        )
        service = VendorStageService(
            profiles_repo=profiles_repo,
            directory_repo=directory_repo,
            hasdata=HasDataClient(settings.hasdata_api_key),
            link_client=link_client,
            report_path=VENDOR_STAGE_REPORT_PATH,
        )

        total = len(pages)
        progress_lock = asyncio.Lock()
        progress_done = 0

        async def stage_one(page: StagePage) -> StageResult:
            nonlocal progress_done
            try:
                result = await service.stage_url(
                    page.page_url, page_title=page.page_title
                )
            except Exception as exc:
                logger.exception("stage failed for %s", page.page_url)
                result = StageResult(
                    page_url=page.page_url, outcome="error", detail=str(exc)
                )
            if page.refs:
                await serp_repo.mark_results_processed(page.refs)

            async with progress_lock:
                progress_done += 1
                done = progress_done
            status = "ok" if result.ok else "failed"
            print(
                f"processing [{done} / {total}] {status} "
                f"{result.outcome} {page.page_url}"
            )
            return result

        results = await map_concurrent(pages, concurrency, stage_one)

        report_path = _write_stage_run_report(
            results,
            model=settings.anthropic_link_filter_model,
            started_at=started_at,
        )

        tallies: dict[str, int] = {}
        profiles_inserted = 0
        total_usage = TokenUsage()
        for result in results:
            tallies[result.outcome] = tallies.get(result.outcome, 0) + 1
            profiles_inserted += result.profiles_inserted
            total_usage = total_usage + result.haiku_usage

        total_haiku_cost = usd_for_model(
            settings.anthropic_link_filter_model, total_usage
        )
        summary = {
            "mode": "sample" if run_sample else "serp",
            "url_count": len(results),
            "profiles_inserted": profiles_inserted,
            "total_haiku_cost_usd": round(total_haiku_cost, 6),
            "run_report_path": str(report_path),
            "skip_report_path": str(VENDOR_STAGE_REPORT_PATH),
            **tallies,
        }
        log_pretty("Vendor stage summary", summary)
        print("Vendor stage summary:")
        for key, value in summary.items():
            print(f"  {key}: {value}")
        return results
    finally:
        await mongo.disconnect()


async def run_scrape_batch(
    *,
    concurrency: int = 3,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[ScrapeOutcome]:
    set_log_stage("vendor_scrape")
    if concurrency < 1:
        raise ValueError("--concurrency must be >= 1")
    if batch_size < 1:
        raise ValueError("--batch-size must be >= 1")

    settings = VendorSettings()
    _log_settings(settings)

    mongo = Mongo(settings.mongo_uri, settings.mongo_db_name)
    await mongo.connect()
    try:
        profiles_repo = VendorsScrapedProfilesRepository(
            mongo.db[settings.vendors_scraped_profiles_collection]
        )
        await profiles_repo.ensure_indexes()

        pages = await profiles_repo.list_scrape_candidates(batch_size)
        if not pages:
            logger.warning(
                "No staged|failed profiles to scrape — nothing to do"
            )
            print("No staged|failed profiles to scrape — nothing to do")
            return []

        total = len(pages)
        logger.info(
            "Vendor scrape: %d URLs batch_size=%d concurrency=%d",
            total,
            batch_size,
            concurrency,
        )

        service = VendorScrapeService(
            profiles_repo=profiles_repo,
            hasdata=HasDataClient(settings.hasdata_api_key),
        )

        progress_lock = asyncio.Lock()
        progress_done = 0

        async def scrape_one(page: dict) -> ScrapeOutcome:
            nonlocal progress_done
            page_url = str(page["page_url"])
            outcome = await service.scrape_url(page_url)
            async with progress_lock:
                progress_done += 1
                done = progress_done
            status = "ok" if outcome.ok else "failed"
            print(
                f"processing [{done} / {total}] {status} {page_url}"
                + (f" | {outcome.detail}" if outcome.detail else "")
            )
            return outcome

        results = await map_concurrent(pages, concurrency, scrape_one)

        ok_count = sum(1 for r in results if r.ok)
        failed_count = total - ok_count
        summary = {
            "url_count": total,
            "scraped_ok": ok_count,
            "failed": failed_count,
        }
        log_pretty("Vendor scrape summary", summary)
        print("Vendor scrape summary:")
        for key, value in summary.items():
            print(f"  {key}: {value}")
        return results
    finally:
        await mongo.disconnect()


def _write_extract_cost_report(
    results: list[ExtractOutcome],
    *,
    model: str,
    started_at: datetime,
) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = started_at.strftime("%Y%m%d_%H%M%S")
    path = OUTPUT_DIR / f"{stamp}_extracted_cost.txt"

    lines: list[str] = [
        f"vendor_profiles extract run — {started_at.isoformat()}",
        f"model: {model}",
        f"urls: {len(results)}",
        "",
        "per_url:",
    ]

    total_usage = TokenUsage()
    extracted = 0
    failed = 0
    skipped = 0
    rules_count = 0
    haiku_count = 0
    for result in results:
        if result.outcome == "extracted":
            extracted += 1
            status = "success"
            if result.extraction_method == "rules":
                rules_count += 1
            elif result.extraction_method == "haiku":
                haiku_count += 1
        elif result.outcome == "skipped":
            skipped += 1
            status = "skipped"
        else:
            failed += 1
            status = "failed"
        cost = usd_for_model(model, result.haiku_usage)
        total_usage = total_usage + result.haiku_usage
        method = result.extraction_method or "-"
        lines.append(
            f"  [{status}] {result.page_url} | outcome={result.outcome}"
            f" | method={method}"
            f" | haiku_input={result.haiku_usage.input_tokens}"
            f" | haiku_output={result.haiku_usage.output_tokens}"
            f" | haiku_cost_usd={cost:.6f}"
            + (f" | detail={result.detail}" if result.detail else "")
        )

    total_cost = usd_for_model(model, total_usage)
    lines.extend(
        [
            "",
            "summary:",
            f"  total_urls: {len(results)}",
            f"  extracted: {extracted}",
            f"  extracted_via_rules: {rules_count}",
            f"  extracted_via_haiku: {haiku_count}",
            f"  skipped: {skipped}",
            f"  failed: {failed}",
            f"  haiku_input_tokens: {total_usage.input_tokens}",
            f"  haiku_output_tokens: {total_usage.output_tokens}",
            f"  total_haiku_cost_usd: {total_cost:.6f}",
        ]
    )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


async def run_extract(
    *,
    concurrency: int = 3,
    run_sample: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[ExtractOutcome]:
    set_log_stage("vendor_extract")
    if concurrency < 1:
        raise ValueError("--concurrency must be >= 1")
    if not run_sample and batch_size < 1:
        raise ValueError("--batch-size must be >= 1")

    settings = VendorSettings()
    _log_settings(settings)

    started_at = datetime.now(timezone.utc)

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

        if run_sample:
            pages = normalize_pages(
                PAGE_URLS, source="vendor_profiles.sample_urls.PAGE_URLS"
            )
            if not pages:
                logger.warning(
                    "sample_urls.PAGE_URLS is empty — nothing to extract"
                )
                return []
            logger.info(
                "Vendor extract (sample): %d URLs concurrency=%d",
                len(pages),
                concurrency,
            )
        else:
            candidates = await profiles_repo.list_extract_candidates(batch_size)
            if not candidates:
                logger.warning(
                    "No scraped profiles to extract — nothing to do"
                )
                print("No scraped profiles to extract — nothing to do")
                return []
            pages = [
                StagePage(page_url=c["page_url"], page_title=None)
                for c in candidates
            ]
            logger.info(
                "Vendor extract (db): %d URLs batch_size=%d concurrency=%d",
                len(pages),
                batch_size,
                concurrency,
            )

        total = len(pages)
        service = VendorExtractService(
            profiles_repo=profiles_repo,
            extracted_repo=extracted_repo,
            extract_client=extract_client,
        )

        progress_lock = asyncio.Lock()
        progress_done = 0

        async def extract_one(page: StagePage) -> ExtractOutcome:
            nonlocal progress_done
            outcome = await service.extract_url(page.page_url)
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
                f"processing [{done} / {total}] {status}{method} {page.page_url}"
                + (f" | {outcome.detail}" if outcome.detail else "")
            )
            if outcome.profile_payload is not None:
                print(
                    json.dumps(
                        {
                            "page_url": outcome.page_url,
                            **outcome.profile_payload,
                        },
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            return outcome

        results = await map_concurrent(pages, concurrency, extract_one)

        report_path = _write_extract_cost_report(
            results,
            model=settings.anthropic_link_filter_model,
            started_at=started_at,
        )

        total_usage = TokenUsage()
        tallies: dict[str, int] = {}
        rules_count = 0
        haiku_count = 0
        for result in results:
            tallies[result.outcome] = tallies.get(result.outcome, 0) + 1
            total_usage = total_usage + result.haiku_usage
            if result.extraction_method == "rules":
                rules_count += 1
            elif result.extraction_method == "haiku":
                haiku_count += 1

        total_haiku_cost = usd_for_model(
            settings.anthropic_link_filter_model, total_usage
        )
        summary = {
            "mode": "sample" if run_sample else "db",
            "url_count": len(results),
            "extracted_via_rules": rules_count,
            "extracted_via_haiku": haiku_count,
            "haiku_input_tokens": total_usage.input_tokens,
            "haiku_output_tokens": total_usage.output_tokens,
            "total_haiku_cost_usd": round(total_haiku_cost, 6),
            "cost_report_path": str(report_path),
            **tallies,
        }
        log_pretty("Vendor extract summary", summary)
        print("Vendor extract summary:")
        for key, value in summary.items():
            print(f"  {key}: {value}")
        return results
    finally:
        await mongo.disconnect()


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(
        prog="python -m vendor_profiles",
        description="Vendor profile SERP discovery and staging pipeline",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    stage_parser = sub.add_parser(
        "stage",
        help=(
            "Stage URLs from SERP results (default) or sample_urls.py (--run-sample)"
        ),
    )
    stage_parser.add_argument(
        "--run-sample",
        action="store_true",
        help="Stage URLs from vendor_profiles/sample_urls.py instead of SERP",
    )
    stage_parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=(
            "Max unprocessed SERP URLs to stage in one run "
            f"(default: {DEFAULT_BATCH_SIZE}; ignored with --run-sample)"
        ),
    )
    stage_parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Max URLs to process in parallel (default: 3)",
    )

    scrape_parser = sub.add_parser(
        "scrape",
        help="Scrape staged|failed vendor profiles via HasData (html+markdown)",
    )
    scrape_parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Max staged|failed profiles to scrape (default: {DEFAULT_BATCH_SIZE})",
    )
    scrape_parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Max URLs to scrape in parallel (default: 3)",
    )

    extract_parser = sub.add_parser(
        "extract",
        help=(
            "Extract structured VendorProfile from scraped markdown "
            "(DB batch by default, or sample_urls with --run-sample; "
            "rule parsers when available, else Haiku)"
        ),
    )
    extract_parser.add_argument(
        "--run-sample",
        action="store_true",
        help="Extract URLs from vendor_profiles/sample_urls.py instead of DB",
    )
    extract_parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=(
            "Max scraped profiles to extract in one run "
            f"(default: {DEFAULT_BATCH_SIZE}; ignored with --run-sample)"
        ),
    )
    extract_parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Max URLs to extract in parallel (default: 3)",
    )

    fetch_parser = sub.add_parser(
        "fetch-serp",
        help="Interactively queue DataForSEO SERP tasks",
    )
    fetch_parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Thread pool size (default: {DEFAULT_WORKERS})",
    )

    poll_parser = sub.add_parser(
        "poll-serp",
        help="Poll queued DataForSEO SERP tasks",
    )
    poll_parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Thread pool size (default: {DEFAULT_WORKERS})",
    )

    args = parser.parse_args()
    try:
        if args.command == "stage":
            set_log_stage("vendor_stage")
            results = asyncio.run(
                run_stage(
                    concurrency=args.concurrency,
                    run_sample=args.run_sample,
                    batch_size=args.batch_size,
                )
            )
            if sum(1 for r in results if r.outcome == "error"):
                sys.exit(1)
        elif args.command == "scrape":
            set_log_stage("vendor_scrape")
            results = asyncio.run(
                run_scrape_batch(
                    concurrency=args.concurrency,
                    batch_size=args.batch_size,
                )
            )
            if sum(1 for r in results if not r.ok):
                sys.exit(1)
        elif args.command == "extract":
            set_log_stage("vendor_extract")
            results = asyncio.run(
                run_extract(
                    concurrency=args.concurrency,
                    run_sample=args.run_sample,
                    batch_size=args.batch_size,
                )
            )
            if sum(1 for r in results if not r.ok):
                sys.exit(1)
        elif args.command == "fetch-serp":
            set_log_stage("vendor_serp")
            run_fetch_serp(workers=args.workers)
        elif args.command == "poll-serp":
            set_log_stage("vendor_serp")
            run_poll_serp(workers=args.workers)
    except Exception as exc:
        logger.exception("%s failed", args.command)
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

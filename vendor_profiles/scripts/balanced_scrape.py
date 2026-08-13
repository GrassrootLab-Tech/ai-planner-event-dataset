"""Select ~47k staged|failed profiles balanced across 7 sources (no Thumbtack),
balanced within each source by SERP category+city, then scrape them via HasData.

Scrape order is source round-robin (one URL per host, then the next wave) so
HasData traffic is spread across sources instead of hammering one host.

Profiles in vendors_scraped_profiles do not store category/city. Those come from
vendor_data_serp_results, matched on page_url or parent_page_url.

Usage:
  python -m vendor_profiles.scripts.balanced_scrape [--concurrency 3]
  python -m vendor_profiles.scripts.balanced_scrape --dry-run
  python -m vendor_profiles.scripts.balanced_scrape --total 47000 --concurrency 5
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from clients.hasdata_client import HasDataClient  # noqa: E402
from db.mongo import Mongo  # noqa: E402
from utils.concurrency import map_concurrent  # noqa: E402
from utils.logger import log_pretty, logger, set_log_stage, setup_logging  # noqa: E402
from utils.url import clean_page_url  # noqa: E402
from vendor_profiles.config import VendorSettings  # noqa: E402
from vendor_profiles.db.profiles_repo import (  # noqa: E402
    SCRAPE_ELIGIBLE_STATUSES,
    VendorsScrapedProfilesRepository,
)
from vendor_profiles.services.scrape_service import (  # noqa: E402
    ScrapeOutcome,
    VendorScrapeService,
)
from vendor_profiles.source_rules import normalize_source_host  # noqa: E402

# Equal share across these hosts only — Thumbtack excluded.
SCRAPE_HOSTS: tuple[str, ...] = (
    "thebash.com",
    "gigsalad.com",
    "partyslate.com",
    "theknot.com",
    "zola.com",
    "weddingwire.com",
    "eventective.com",
)

DEFAULT_TOTAL = 47_000
DEFAULT_CONCURRENCY = 3
CANDIDATE_BATCH_SIZE = 100
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output"


@dataclass
class ProfileCandidate:
    page_url: str
    host: str
    category_slug: str = ""
    city_slug: str = ""
    parent_page_url: str | None = None


def _per_source_quotas(total: int, hosts: tuple[str, ...]) -> dict[str, int]:
    """Split total as evenly as possible across hosts (remainder goes to first hosts)."""
    n = len(hosts)
    base, rem = divmod(total, n)
    return {host: base + (1 if i < rem else 0) for i, host in enumerate(hosts)}


def _round_robin_cat_city(
    candidates: list[ProfileCandidate], limit: int
) -> list[ProfileCandidate]:
    """Even mix of (category, city) buckets within one source."""
    buckets: dict[tuple[str, str], deque[ProfileCandidate]] = defaultdict(deque)
    for c in candidates:
        buckets[(c.category_slug, c.city_slug)].append(c)

    queues = list(buckets.values())
    selected: list[ProfileCandidate] = []
    while queues and len(selected) < limit:
        next_queues: list[deque[ProfileCandidate]] = []
        for queue in queues:
            if len(selected) >= limit:
                break
            selected.append(queue.popleft())
            if queue:
                next_queues.append(queue)
        queues = next_queues
    return selected


async def _build_serp_meta(
    serp_coll,
) -> dict[str, tuple[str, str]]:
    """Map cleaned result URL / lookup key -> (category_slug, city_slug)."""
    meta: dict[str, tuple[str, str]] = {}
    cursor = serp_coll.find(
        {"status": "ok", "results.0": {"$exists": True}},
        {
            "results.url": 1,
            "category": 1,
            "category_slug": 1,
            "city": 1,
            "city_slug": 1,
        },
    )
    async for doc in cursor:
        category = str(doc.get("category_slug") or doc.get("category") or "")
        city = str(doc.get("city_slug") or doc.get("city") or "")
        for item in doc.get("results") or []:
            if not isinstance(item, dict):
                continue
            raw = item.get("url")
            if not isinstance(raw, str) or not raw.strip():
                continue
            cleaned = clean_page_url(raw.strip())
            if cleaned and cleaned not in meta:
                meta[cleaned] = (category, city)
    return meta


async def _load_candidates(
    profiles_coll,
    serp_meta: dict[str, tuple[str, str]],
) -> dict[str, list[ProfileCandidate]]:
    """Load scrape-eligible profiles per host (Thumbtack never included).

    Pages Mongo in batches of CANDIDATE_BATCH_SIZE via ``_id`` range queries,
    then combines everything in memory for balanced selection.
    """
    by_host: dict[str, list[ProfileCandidate]] = {h: [] for h in SCRAPE_HOSTS}
    host_set = set(SCRAPE_HOSTS)
    projection = {"_id": 1, "page_url": 1, "parent_page_url": 1, "status": 1}

    last_id = None
    scanned = 0
    while True:
        query: dict[str, Any] = {
            "status": {"$in": list(SCRAPE_ELIGIBLE_STATUSES)},
        }
        if last_id is not None:
            query["_id"] = {"$gt": last_id}

        batch = await (
            profiles_coll.find(query, projection)
            .sort("_id", 1)
            .limit(CANDIDATE_BATCH_SIZE)
            .to_list(length=CANDIDATE_BATCH_SIZE)
        )
        if not batch:
            break

        for doc in batch:
            page_url = doc.get("page_url")
            if not isinstance(page_url, str) or not page_url.strip():
                continue
            host = normalize_source_host(page_url)
            if host not in host_set:
                continue

            parent = doc.get("parent_page_url")
            parent_url = (
                parent.strip()
                if isinstance(parent, str) and parent.strip()
                else None
            )

            cat, city = ("", "")
            if page_url in serp_meta:
                cat, city = serp_meta[page_url]
            elif parent_url and parent_url in serp_meta:
                cat, city = serp_meta[parent_url]

            by_host[host].append(
                ProfileCandidate(
                    page_url=page_url,
                    host=host,
                    category_slug=cat,
                    city_slug=city,
                    parent_page_url=parent_url,
                )
            )

        last_id = batch[-1]["_id"]
        scanned += len(batch)
        if scanned % 5_000 == 0:
            logger.info(
                "Candidate load progress: scanned %d docs…",
                scanned,
            )

    logger.info(
        "Candidate load done: scanned %d docs, kept %d across hosts",
        scanned,
        sum(len(v) for v in by_host.values()),
    )
    return by_host


def _select_balanced(
    by_host: dict[str, list[ProfileCandidate]],
    quotas: dict[str, int],
) -> list[ProfileCandidate]:
    """Pick quotas per host (cat×city balanced), then interleave sources for scrape order.

    Scrape order is host round-robin: one from each source, then the next wave,
    so consecutive requests do not hammer a single host.
    """
    per_host: dict[str, list[ProfileCandidate]] = {}
    for host in SCRAPE_HOSTS:
        quota = quotas[host]
        pool = by_host.get(host) or []
        if len(pool) < quota:
            logger.warning(
                "Host %s has only %d eligible profiles (quota %d) — taking all",
                host,
                len(pool),
                quota,
            )
        per_host[host] = _round_robin_cat_city(pool, min(quota, len(pool)))

    queues = {
        host: deque(per_host[host])
        for host in SCRAPE_HOSTS
        if per_host.get(host)
    }
    order = [h for h in SCRAPE_HOSTS if h in queues]
    interleaved: list[ProfileCandidate] = []
    while order:
        next_order: list[str] = []
        for host in order:
            queue = queues[host]
            interleaved.append(queue.popleft())
            if queue:
                next_order.append(host)
        order = next_order
    return interleaved


def _write_selection_report(
    selected: list[ProfileCandidate],
    *,
    quotas: dict[str, int],
    available: dict[str, int],
    dry_run: bool,
) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUTPUT_DIR / f"{stamp}_balanced_scrape_selection.txt"

    by_host = Counter(c.host for c in selected)
    by_host_cat_city: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)
    for c in selected:
        by_host_cat_city[c.host][(c.category_slug, c.city_slug)] += 1

    lines = [
        f"balanced scrape selection — {datetime.now(timezone.utc).isoformat()}",
        f"dry_run: {dry_run}",
        f"selected_total: {len(selected)}",
        "",
        "per_host:",
    ]
    for host in SCRAPE_HOSTS:
        lines.append(
            f"  {host}: selected={by_host[host]} quota={quotas[host]} "
            f"available={available.get(host, 0)}"
        )

    lines.append("")
    lines.append("per_host category×city bucket counts:")
    for host in SCRAPE_HOSTS:
        lines.append(f"  [{host}]")
        buckets = by_host_cat_city[host]
        for (cat, city), n in sorted(buckets.items(), key=lambda x: (-x[1], x[0])):
            cat_l = cat or "(unknown)"
            city_l = city or "(unknown)"
            lines.append(f"    {cat_l} × {city_l}: {n}")

    lines.append("")
    lines.append("urls (scrape order — source round-robin):")
    for c in selected:
        lines.append(c.page_url)

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


async def run_balanced_scrape(
    *,
    total: int = DEFAULT_TOTAL,
    concurrency: int = DEFAULT_CONCURRENCY,
    dry_run: bool = False,
) -> list[ScrapeOutcome]:
    set_log_stage("vendor_balanced_scrape")
    if total < 1:
        raise ValueError("--total must be >= 1")
    if concurrency < 1:
        raise ValueError("--concurrency must be >= 1")

    settings = VendorSettings()
    quotas = _per_source_quotas(total, SCRAPE_HOSTS)
    log_pretty(
        "Balanced scrape plan",
        {
            "total_target": total,
            "hosts": list(SCRAPE_HOSTS),
            "quotas": quotas,
            "concurrency": concurrency,
            "dry_run": dry_run,
        },
    )

    mongo = Mongo(settings.mongo_uri, settings.mongo_db_name)
    await mongo.connect()
    try:
        profiles_coll = mongo.db[settings.vendors_scraped_profiles_collection]
        serp_coll = mongo.db[settings.vendor_data_serp_results_collection]

        logger.info("Building SERP category/city lookup…")
        serp_meta = await _build_serp_meta(serp_coll)
        logger.info("SERP URL meta entries: %d", len(serp_meta))

        logger.info("Loading staged|failed profiles for %d hosts…", len(SCRAPE_HOSTS))
        by_host = await _load_candidates(profiles_coll, serp_meta)
        available = {h: len(by_host[h]) for h in SCRAPE_HOSTS}
        log_pretty("Eligible profiles by host", available)

        selected = _select_balanced(by_host, quotas)
        report_path = _write_selection_report(
            selected,
            quotas=quotas,
            available=available,
            dry_run=dry_run,
        )
        logger.info(
            "Selected %d profiles — report: %s", len(selected), report_path
        )
        print(f"Selected {len(selected)} profiles")
        print(f"Selection report: {report_path}")
        for host in SCRAPE_HOSTS:
            n = sum(1 for c in selected if c.host == host)
            print(
                f"  {host}: {n} / quota {quotas[host]} "
                f"(available {available[host]})"
            )

        if dry_run:
            print("Dry run — not scraping")
            return []

        if not selected:
            print("Nothing to scrape")
            return []

        profiles_repo = VendorsScrapedProfilesRepository(profiles_coll)
        await profiles_repo.ensure_indexes()
        service = VendorScrapeService(
            profiles_repo=profiles_repo,
            hasdata=HasDataClient(settings.hasdata_api_key),
        )

        total_n = len(selected)
        progress_lock = asyncio.Lock()
        progress_done = 0

        async def scrape_one(candidate: ProfileCandidate) -> ScrapeOutcome:
            nonlocal progress_done
            outcome = await service.scrape_url(candidate.page_url)
            async with progress_lock:
                progress_done += 1
                done = progress_done
            status = "ok" if outcome.ok else "failed"
            print(
                f"processing [{done} / {total_n}] {status} {candidate.page_url}"
                + (f" | {outcome.detail}" if outcome.detail else "")
            )
            return outcome

        results = await map_concurrent(selected, concurrency, scrape_one)
        ok_count = sum(1 for r in results if r.ok)
        summary = {
            "selected": total_n,
            "scraped_ok": ok_count,
            "failed": total_n - ok_count,
            "report": str(report_path),
        }
        log_pretty("Balanced scrape summary", summary)
        print("Balanced scrape summary:")
        for key, value in summary.items():
            print(f"  {key}: {value}")
        return results
    finally:
        await mongo.disconnect()


def main(argv: list[str] | None = None) -> None:
    setup_logging()
    parser = argparse.ArgumentParser(
        description=(
            "Select equal shares of staged|failed profiles across 7 sources "
            "(excluding Thumbtack), balance by category×city within each source, "
            "then scrape via HasData."
        )
    )
    parser.add_argument(
        "--total",
        type=int,
        default=DEFAULT_TOTAL,
        help=f"Total profiles to select (default: {DEFAULT_TOTAL})",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"Parallel HasData scrapes (default: {DEFAULT_CONCURRENCY})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Select and write report only — do not scrape",
    )
    args = parser.parse_args(argv)
    asyncio.run(
        run_balanced_scrape(
            total=args.total,
            concurrency=args.concurrency,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()

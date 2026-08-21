"""Queue The Knot vendor-content-api Google SERP tasks via DataForSEO standard queue.

One query per category (no city):
  site:theknot.com/vendor-content-api/api Photographers

Uses task_post (standard priority, ~5 min TAT) — not the live endpoint.
Results land in the_knot_pricing_pdfs; poll with poll_theknot_api_serp

Usage:
  python -m vendor_profiles.scripts.fetch_theknot_api_serp
  python -m vendor_profiles.scripts.fetch_theknot_api_serp --yes --workers 8
  python -m vendor_profiles.scripts.fetch_theknot_api_serp --dry-run
"""

from __future__ import annotations

import argparse
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS_ROOT = ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from fetch_serp_results import (  # noqa: E402
    DEFAULT_WORKERS,
    queue_serp_task,
    should_skip,
    upsert_doc,
)
from vendor_profiles.config import VendorSettings  # noqa: E402
from vendor_profiles.sources import CATEGORIES  # noqa: E402

THEKNOT_API_SITE = "theknot.com/vendor-content-api/api"
SOURCE_URL = f"https://www.{THEKNOT_API_SITE}"
DEPTH = 300


def build_search_query(category: str) -> str:
    return f"site:{THEKNOT_API_SITE} {category}"


def run_fetch_theknot_api_serp(
    *,
    workers: int = DEFAULT_WORKERS,
    dry_run: bool = False,
    yes: bool = False,
) -> None:
    if workers < 1:
        raise SystemExit("--workers must be >= 1")

    total = len(CATEGORIES)
    print(
        f"The Knot vendor-content-api SERP (by category)\n"
        f"  categories: {total}\n"
        f"  depth: {DEPTH}\n"
        f"  workers: {workers}\n"
        f"  collection: the_knot_pricing_pdfs\n"
        f"  example: {build_search_query('Photographers')!r}"
    )

    if dry_run:
        for category in CATEGORIES[:5]:
            print(f"  dry-run: {build_search_query(category['name'])}")
        if total > 5:
            print(f"  ... and {total - 5} more")
        return

    if not yes:
        confirm = input(f"\nQueue {total} DataForSEO tasks? [Y/n]: ").strip().lower()
        if confirm in ("n", "no"):
            raise SystemExit("Aborted.")

    settings = VendorSettings()
    if not settings.dataforseo_login or not settings.dataforseo_password:
        raise SystemExit(
            "DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD must be set in the environment / .env"
        )

    client = MongoClient(settings.mongo_uri)
    collection = client[settings.mongo_db_name][
        settings.the_knot_pricing_pdfs_collection
    ]
    lock = threading.Lock()

    def process_category(category: dict[str, str]) -> tuple[str, str, str, str, str]:
        search_query = build_search_query(category["name"])
        if should_skip(collection, search_query):
            return search_query, "skipped", "", "", ""

        base_doc = {
            "search_query": search_query,
            "source_url": SOURCE_URL,
            "category": category["name"],
            "category_slug": category["slug"],
            "serp_kind": "theknot_vendor_content_api",
            "depth": DEPTH,
        }
        try:
            task_id = queue_serp_task(
                settings.dataforseo_login,
                settings.dataforseo_password,
                search_query,
                depth=DEPTH,
            )
            doc = {
                **base_doc,
                "task_id": task_id,
                "results": [],
                "status": "queued",
            }
            with lock:
                doc_id = upsert_doc(collection, search_query, doc)
            return search_query, "queued", task_id, doc_id, ""
        except Exception as exc:
            error_msg = str(exc)
            doc = {
                **base_doc,
                "task_id": None,
                "results": [],
                "status": "failed",
                "error": error_msg,
            }
            with lock:
                doc_id = upsert_doc(collection, search_query, doc)
            return search_query, "failed", "", doc_id, error_msg

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(process_category, category): category
            for category in CATEGORIES
        }
        done = 0
        for future in as_completed(futures):
            done += 1
            category = futures[future]
            try:
                search_query, status, task_id, doc_id, error_msg = future.result()
                if status == "skipped":
                    print(f"[{done}/{total}] skipped (already in db): {search_query}")
                elif status == "failed":
                    print(
                        f"[{done}/{total}] failed, stored {doc_id}: {error_msg} | "
                        f"{search_query}"
                    )
                else:
                    print(
                        f"[{done}/{total}] queued task_id={task_id}, stored {doc_id} | "
                        f"{search_query}"
                    )
            except Exception as exc:
                print(f"[{done}/{total}] failed: {exc} | {category['name']}")

    client.close()
    print(
        "Done. Poll results with: "
        "python3 -m vendor_profiles.scripts.poll_theknot_api_serp"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Queue The Knot vendor-content-api SERP tasks for all categories"
        )
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Thread pool size (default: {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print sample queries without calling DataForSEO",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    args = parser.parse_args()
    run_fetch_theknot_api_serp(
        workers=args.workers,
        dry_run=args.dry_run,
        yes=args.yes,
    )


if __name__ == "__main__":
    main()

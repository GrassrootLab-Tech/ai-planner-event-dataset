"""Queue Google SERP tasks via DataForSEO standard queue and store them in MongoDB.

Uses standard (normal) priority ~5 min TAT — not high-priority queue.
Live endpoint helper is kept for reuse; this CLI posts to task_post only.

Poll results with: python scripts/poll_serp_results.py
"""

from __future__ import annotations

import argparse
import csv
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx
from pymongo import MongoClient
from pymongo.collection import Collection

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Settings

DATAFORSEO_LIVE_URL = "https://api.dataforseo.com/v3/serp/google/organic/live/regular"
DATAFORSEO_TASK_POST_URL = "https://api.dataforseo.com/v3/serp/google/organic/task_post"
DATAFORSEO_TASK_GET_URL = (
    "https://api.dataforseo.com/v3/serp/google/organic/task_get/regular"
)
LOCATION_CODE_US = 2840
LANGUAGE_CODE = "en"
DEPTH = 100
# 1 = standard/normal priority (~5 min). Do not use 2 (high priority).
PRIORITY_STANDARD = 1
DEFAULT_WORKERS = 4
DEFAULT_CSV = ROOT / "scripts" / "partyhub-idea-domains-final.csv"
NO_SEARCH_RESULTS_CODE = 40102
TASK_CREATED_CODE = 20100
# Task still processing — leave status as queued
TASK_PENDING_CODES = {40601, 40602}


def normalize_url(url: str) -> str:
    return url.strip().rstrip("/")


def load_sources(csv_path: Path) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            base_url = (row.get("base_url") or "").strip()
            operator = (row.get("google_search_operator") or "").strip()
            if not base_url or not operator:
                continue
            key = normalize_url(base_url)
            if key in seen:
                continue
            seen.add(key)
            sources.append({"base_url": base_url, "google_search_operator": operator})
    return sources


def find_source_by_url(
    sources: list[dict[str, str]], url: str
) -> dict[str, str] | None:
    target = normalize_url(url)
    for source in sources:
        if normalize_url(source["base_url"]) == target:
            return source
    return None


def _serp_payload(query: str) -> list[dict[str, Any]]:
    return [
        {
            "keyword": query,
            "location_code": LOCATION_CODE_US,
            "language_code": LANGUAGE_CODE,
            "depth": DEPTH,
            "priority": PRIORITY_STANDARD,
        }
    ]


def parse_organic_items(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    organic: list[dict[str, Any]] = []
    for item in items or []:
        if item.get("type") != "organic":
            continue
        organic.append(
            {
                "rank": item.get("rank_absolute"),
                "url": item.get("url"),
                "title": item.get("title"),
                "description": item.get("description"),
            }
        )
        if len(organic) >= DEPTH:
            break
    return organic


def parse_organic_from_task(task: dict[str, Any]) -> list[dict[str, Any]]:
    results = task.get("result") or []
    if not results:
        return []
    return parse_organic_items(results[0].get("items"))


def fetch_serp_live(login: str, password: str, query: str) -> list[dict[str, Any]]:
    """Live endpoint (kept for reuse). Main CLI uses the standard queue instead."""
    payload = [
        {
            "keyword": query,
            "location_code": LOCATION_CODE_US,
            "language_code": LANGUAGE_CODE,
            "depth": DEPTH,
        }
    ]
    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            DATAFORSEO_LIVE_URL,
            json=payload,
            auth=(login, password),
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        data = response.json()

    if data.get("status_code") != 20000:
        if data.get("status_code") == NO_SEARCH_RESULTS_CODE:
            return []
        raise RuntimeError(
            f"DataForSEO error: {data.get('status_code')} {data.get('status_message')}"
        )

    tasks = data.get("tasks") or []
    if not tasks:
        return []

    task = tasks[0]
    task_status = task.get("status_code")
    if task_status == NO_SEARCH_RESULTS_CODE:
        return []
    if task_status != 20000:
        raise RuntimeError(
            f"DataForSEO task error: {task_status} {task.get('status_message')}"
        )
    return parse_organic_from_task(task)


def queue_serp_task(login: str, password: str, query: str) -> str:
    """Post to standard queue (priority=1). Returns DataForSEO task id."""
    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            DATAFORSEO_TASK_POST_URL,
            json=_serp_payload(query),
            auth=(login, password),
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        data = response.json()

    if data.get("status_code") != 20000:
        raise RuntimeError(
            f"DataForSEO error: {data.get('status_code')} {data.get('status_message')}"
        )

    tasks = data.get("tasks") or []
    if not tasks:
        raise RuntimeError("DataForSEO task_post returned no tasks")

    task = tasks[0]
    task_status = task.get("status_code")
    if task_status not in (TASK_CREATED_CODE, 20000):
        raise RuntimeError(
            f"DataForSEO task_post error: {task_status} {task.get('status_message')}"
        )

    task_id = task.get("id")
    if not task_id:
        raise RuntimeError("DataForSEO task_post returned no task id")
    return str(task_id)


def get_serp_task(
    login: str, password: str, task_id: str
) -> tuple[str, list[dict[str, Any]], str]:
    """Fetch a queued task result.

    Returns (outcome, results, error) where outcome is:
      - "ok"      ready (including empty / 40102)
      - "pending" still in queue (40601/40602)
      - "failed"  real error
    """
    url = f"{DATAFORSEO_TASK_GET_URL}/{task_id}"
    with httpx.Client(timeout=60.0) as client:
        response = client.get(url, auth=(login, password))
        response.raise_for_status()
        data = response.json()

    if data.get("status_code") != 20000:
        code = data.get("status_code")
        if code in TASK_PENDING_CODES:
            return "pending", [], ""
        if code == NO_SEARCH_RESULTS_CODE:
            return "ok", [], ""
        return (
            "failed",
            [],
            f"DataForSEO error: {code} {data.get('status_message')}",
        )

    tasks = data.get("tasks") or []
    if not tasks:
        return "failed", [], "DataForSEO task_get returned no tasks"

    task = tasks[0]
    task_status = task.get("status_code")
    if task_status in TASK_PENDING_CODES:
        return "pending", [], ""
    if task_status == NO_SEARCH_RESULTS_CODE:
        return "ok", [], ""
    if task_status != 20000:
        return (
            "failed",
            [],
            f"DataForSEO task error: {task_status} {task.get('status_message')}",
        )
    return "ok", parse_organic_from_task(task), ""


def should_skip(collection: Collection, search_query: str) -> bool:
    """Queue only when missing or failed (skip ok / queued / anything else)."""
    doc = collection.find_one({"search_query": search_query}, {"status": 1})
    if doc is None:
        return False
    return doc.get("status") != "failed"


def upsert_doc(collection: Collection, search_query: str, doc: dict[str, Any]) -> str:
    result = collection.replace_one({"search_query": search_query}, doc, upsert=True)
    if result.upserted_id is not None:
        return str(result.upserted_id)
    existing = collection.find_one({"search_query": search_query}, {"_id": 1})
    return str(existing["_id"]) if existing else ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Queue Google SERP tasks via DataForSEO standard queue into MongoDB."
        )
    )
    parser.add_argument(
        "--keyword", required=True, help="Keyword after the search operator"
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Single base_url matching a CSV row (one-source run)",
    )
    parser.add_argument(
        "--csv",
        default=str(DEFAULT_CSV),
        help="CSV of sources with google_search_operator and base_url",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Thread pool size for batch runs (default: {DEFAULT_WORKERS})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.workers < 1:
        raise SystemExit("--workers must be >= 1")

    settings = Settings()
    if not settings.dataforseo_login or not settings.dataforseo_password:
        raise SystemExit(
            "DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD must be set in the environment / .env"
        )

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"CSV file not found: {csv_path}")

    sources = load_sources(csv_path)
    if not sources:
        raise SystemExit(f"No sources found in {csv_path}")

    if args.url:
        source = find_source_by_url(sources, args.url)
        if source is None:
            raise SystemExit(f"No CSV row with base_url matching --url: {args.url}")
        sources = [source]

    client = MongoClient(settings.mongo_uri)
    collection = client[settings.mongo_db_name][
        settings.event_data_serp_results_collection
    ]
    lock = threading.Lock()
    total = len(sources)

    print(
        f"Queue sources: {total} | keyword={args.keyword!r} | "
        f"depth={DEPTH} | priority={PRIORITY_STANDARD} (standard) | "
        f"workers={args.workers}"
    )

    def process_source(
        source: dict[str, str],
    ) -> tuple[str, str, str, str, str]:
        search_query = f"{source['google_search_operator']} {args.keyword}".strip()
        if should_skip(collection, search_query):
            return source["base_url"], "skipped", "", "", ""

        base_doc = {
            "search_query": search_query,
            "keyword_used": args.keyword,
            "base_website_url": source["base_url"],
        }
        try:
            task_id = queue_serp_task(
                settings.dataforseo_login,
                settings.dataforseo_password,
                search_query,
            )
            doc = {
                **base_doc,
                "task_id": task_id,
                "results": [],
                "status": "queued",
            }
            with lock:
                doc_id = upsert_doc(collection, search_query, doc)
            return source["base_url"], "queued", task_id, doc_id, ""
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
            return source["base_url"], "failed", "", doc_id, error_msg

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(process_source, source): source for source in sources
        }
        done = 0
        for future in as_completed(futures):
            done += 1
            source = futures[future]
            base_url = source["base_url"]
            try:
                base_url, status, task_id, doc_id, error_msg = future.result()
                if status == "skipped":
                    print(f"[{done}/{total}] {base_url} skipped (already in db)")
                elif status == "failed":
                    print(
                        f"[{done}/{total}] {base_url} failed, stored {doc_id}: {error_msg}"
                    )
                else:
                    print(
                        f"[{done}/{total}] {base_url} queued task_id={task_id}, "
                        f"stored {doc_id}"
                    )
            except Exception as exc:
                print(f"[{done}/{total}] {base_url} failed: {exc}")

    client.close()
    print("Done. Run scripts/poll_serp_results.py to collect ready results.")


if __name__ == "__main__":
    main()

"""Queue vendor-profile Google SERP tasks via DataForSEO standard queue.

Interactive: paste one allowlisted source, then city/category index slices.
"""

from __future__ import annotations

import argparse
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx
from pymongo import MongoClient
from pymongo.collection import Collection

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS_ROOT = ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from fetch_serp_results import (  # noqa: E402
    DATAFORSEO_TASK_POST_URL,
    DEFAULT_WORKERS,
    DEPTH,
    LANGUAGE_CODE,
    LOCATION_CODE_US,
    PRIORITY_STANDARD,
    TASK_CREATED_CODE,
    upsert_doc,
)
from vendor_profiles.config import VendorSettings  # noqa: E402
from vendor_profiles.source_rules import (  # noqa: E402
    normalize_source_host,
)
from vendor_profiles.sources import CATEGORIES, CITIES, SOURCES  # noqa: E402

DEFAULT_CITY_END = 5
DEFAULT_CATEGORY_END = 5


def resolve_source(pasted: str) -> str | None:
    target = normalize_source_host(pasted)
    if not target:
        return None
    for source in SOURCES:
        if normalize_source_host(source) == target:
            return source
    return None


def build_search_query(source_url: str, category: str, city: str) -> str:
    return f"site:{source_url} {category} in {city} CO"


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


def queue_serp_task(login: str, password: str, query: str) -> str:
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


def already_exists(collection: Collection, search_query: str) -> bool:
    return collection.find_one({"search_query": search_query}, {"_id": 1}) is not None


def prompt_int(label: str, default: int) -> int:
    raw = input(f"{label} [{default}]: ").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"Invalid integer for {label}: {raw!r}") from exc


def prompt_slice(
    name: str, items: list[dict[str, str]], default_end: int
) -> list[dict[str, str]]:
    n = len(items)
    end_default = min(default_end, n)
    print(f"\n{name}: {n} total (indices 0..{n - 1})")
    if n:
        preview = ", ".join(item["name"] for item in items[:3])
        print(f"  first: {preview}{'...' if n > 3 else ''}")
    start = prompt_int(f"{name} start index", 0)
    end = prompt_int(f"{name} end index", end_default)
    if not (0 <= start < end <= n):
        raise SystemExit(
            f"Invalid {name} slice [{start}:{end}] — need 0 <= start < end <= {n}"
        )
    selected = items[start:end]
    print(f"  using [{start}:{end}] → {len(selected)} {name.lower()}")
    return selected


def prompt_source() -> str:
    print("Allowed sources:")
    for source in SOURCES:
        print(f"  - {source}")
    pasted = input("\nPaste source URL: ").strip()
    if not pasted:
        raise SystemExit("No source URL provided.")
    canonical = resolve_source(pasted)
    if canonical is None:
        raise SystemExit(
            f"Source not in allowlist: {pasted!r}\n"
            "Allowed:\n" + "\n".join(f"  - {s}" for s in SOURCES)
        )
    print(f"Matched source: {canonical}")
    return canonical


def run_fetch_serp(*, workers: int = DEFAULT_WORKERS) -> None:
    if workers < 1:
        raise SystemExit("--workers must be >= 1")

    settings = VendorSettings()
    if not settings.dataforseo_login or not settings.dataforseo_password:
        raise SystemExit(
            "DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD must be set in the environment / .env"
        )

    source_url = prompt_source()
    cities = prompt_slice("Cities", CITIES, DEFAULT_CITY_END)
    categories = prompt_slice("Categories", CATEGORIES, DEFAULT_CATEGORY_END)

    jobs = [(category, city) for city in cities for category in categories]
    total = len(jobs)
    print(
        f"\nWill queue up to {total} queries "
        f"(source={source_url}, depth={DEPTH}, workers={workers})"
    )
    confirm = input("Continue? [Y/n]: ").strip().lower()
    if confirm in ("n", "no"):
        raise SystemExit("Aborted.")

    client = MongoClient(settings.mongo_uri)
    collection = client[settings.mongo_db_name][
        settings.vendor_data_serp_results_collection
    ]
    lock = threading.Lock()

    def process_job(
        category: dict[str, str], city: dict[str, str]
    ) -> tuple[str, str, str, str, str]:
        search_query = build_search_query(source_url, category["name"], city["name"])
        if already_exists(collection, search_query):
            return search_query, "skipped", "", "", ""

        base_doc = {
            "search_query": search_query,
            "source_url": source_url,
            "category": category["name"],
            "category_slug": category["slug"],
            "city": city["name"],
            "city_slug": city["slug"],
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
            executor.submit(process_job, category, city): (category, city)
            for category, city in jobs
        }
        done = 0
        for future in as_completed(futures):
            done += 1
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
                category, city = futures[future]
                print(
                    f"[{done}/{total}] failed: {exc} | "
                    f"{category['name']} in {city['name']}"
                )

    client.close()
    print("Done. Run: python -m vendor_profiles poll-serp")


def main() -> None:
    parser = argparse.ArgumentParser(description="Queue vendor SERP tasks")
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Thread pool size (default: {DEFAULT_WORKERS})",
    )
    args = parser.parse_args()
    run_fetch_serp(workers=args.workers)


if __name__ == "__main__":
    main()

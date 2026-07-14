"""One-shot poll of queued DataForSEO SERP tasks; update Mongo docs to ok/failed."""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
for path in (ROOT, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from config import Settings
from fetch_serp_results import DEFAULT_WORKERS, get_serp_task


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-shot poll of status=queued SERP docs and fill results."
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Thread pool size (default: {DEFAULT_WORKERS})",
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

    client = MongoClient(settings.mongo_uri)
    collection = client[settings.mongo_db_name][
        settings.event_data_serp_results_collection
    ]

    queued = list(collection.find({"status": "queued"}))
    total = len(queued)
    print(f"Queued docs: {total} | workers={args.workers}")

    if total == 0:
        client.close()
        print("Nothing to poll. Done.")
        return

    def process_doc(doc: dict) -> tuple[str, str, int, str]:
        search_query = doc.get("search_query") or ""
        base_url = doc.get("base_website_url") or search_query
        task_id = doc.get("task_id")
        if not task_id:
            collection.update_one(
                {"_id": doc["_id"]},
                {
                    "$set": {
                        "status": "failed",
                        "results": [],
                        "error": "missing task_id",
                    }
                },
            )
            return base_url, "failed", 0, "missing task_id"

        outcome, results, error_msg = get_serp_task(
            settings.dataforseo_login,
            settings.dataforseo_password,
            str(task_id),
        )
        if outcome == "pending":
            return base_url, "pending", 0, ""
        if outcome == "ok":
            collection.update_one(
                {"_id": doc["_id"]},
                {
                    "$set": {"status": "ok", "results": results},
                    "$unset": {"error": ""},
                },
            )
            return base_url, "ok", len(results), ""
        collection.update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "status": "failed",
                    "results": [],
                    "error": error_msg,
                }
            },
        )
        return base_url, "failed", 0, error_msg

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_doc, doc): doc for doc in queued}
        done = 0
        for future in as_completed(futures):
            done += 1
            doc = futures[future]
            base_url = doc.get("base_website_url") or "?"
            try:
                base_url, status, got, error_msg = future.result()
                if status == "pending":
                    print(f"[{done}/{total}] {base_url} still queued")
                elif status == "failed":
                    print(
                        f"[{done}/{total}] {base_url} failed: {error_msg}"
                    )
                else:
                    print(f"[{done}/{total}] {base_url} ok, got {got}")
            except Exception as exc:
                print(f"[{done}/{total}] {base_url} failed: {exc}")

    client.close()
    print("Done.")


if __name__ == "__main__":
    main()

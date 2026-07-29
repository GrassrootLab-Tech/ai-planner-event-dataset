"""One-shot poll of queued vendor-profile DataForSEO SERP tasks."""

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
from fetch_vendor_serp_results import DEPTH


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "One-shot poll of status=queued vendor SERP docs and fill results."
        )
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
        settings.vendor_data_serp_results_collection
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
        label = doc.get("source_url") or search_query
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
            return label, "failed", 0, "missing task_id"

        outcome, results, error_msg = get_serp_task(
            settings.dataforseo_login,
            settings.dataforseo_password,
            str(task_id),
        )
        if outcome == "pending":
            return label, "pending", 0, ""
        if outcome == "ok":
            capped = results[:DEPTH]
            collection.update_one(
                {"_id": doc["_id"]},
                {
                    "$set": {"status": "ok", "results": capped},
                    "$unset": {"error": ""},
                },
            )
            return label, "ok", len(capped), ""
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
        return label, "failed", 0, error_msg

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_doc, doc): doc for doc in queued}
        done = 0
        for future in as_completed(futures):
            done += 1
            doc = futures[future]
            label = doc.get("source_url") or doc.get("search_query") or "?"
            try:
                label, status, got, error_msg = future.result()
                if status == "pending":
                    print(f"[{done}/{total}] {label} still queued")
                elif status == "failed":
                    print(f"[{done}/{total}] {label} failed: {error_msg}")
                else:
                    print(f"[{done}/{total}] {label} ok, got {got}")
            except Exception as exc:
                print(f"[{done}/{total}] {label} failed: {exc}")

    client.close()
    print("Done.")


if __name__ == "__main__":
    main()

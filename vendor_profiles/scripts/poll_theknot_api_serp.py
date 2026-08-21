"""Poll queued The Knot pricing PDF SERP tasks from the_knot_pricing_pdfs."""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS_ROOT = ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from fetch_serp_results import DEFAULT_WORKERS, get_serp_task  # noqa: E402
from vendor_profiles.config import VendorSettings  # noqa: E402

DEFAULT_THEKNOT_DEPTH = 300


def run_poll_theknot_api_serp(*, workers: int = DEFAULT_WORKERS) -> None:
    if workers < 1:
        raise SystemExit("--workers must be >= 1")

    settings = VendorSettings()
    if not settings.dataforseo_login or not settings.dataforseo_password:
        raise SystemExit(
            "DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD must be set in the environment / .env"
        )

    client = MongoClient(settings.mongo_uri)
    collection = client[settings.mongo_db_name][
        settings.the_knot_pricing_pdfs_collection
    ]

    queued = list(collection.find({"status": "queued"}))
    total = len(queued)
    print(
        f"Collection: {settings.the_knot_pricing_pdfs_collection} | "
        f"queued docs: {total} | workers={workers}"
    )

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

        doc_depth = doc.get("depth")
        depth = int(doc_depth) if isinstance(doc_depth, int) else DEFAULT_THEKNOT_DEPTH

        outcome, results, error_msg = get_serp_task(
            settings.dataforseo_login,
            settings.dataforseo_password,
            str(task_id),
            depth=depth,
        )
        if outcome == "pending":
            return label, "pending", 0, ""
        if outcome == "ok":
            capped = results[:depth]
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

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_doc, doc): doc for doc in queued}
        done = 0
        for future in as_completed(futures):
            done += 1
            doc = futures[future]
            label = doc.get("search_query") or doc.get("source_url") or "?"
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Poll The Knot pricing PDF SERP tasks"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Thread pool size (default: {DEFAULT_WORKERS})",
    )
    args = parser.parse_args()
    run_poll_theknot_api_serp(workers=args.workers)


if __name__ == "__main__":
    main()

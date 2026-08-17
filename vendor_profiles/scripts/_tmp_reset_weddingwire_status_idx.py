"""One-off: reset weddingwire extracted -> scraped via status+_id index."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pymongo import ASCENDING, MongoClient
from pymongo.errors import PyMongoError

from vendor_profiles.config import VendorSettings

PAGE = 1000
UPDATE_BATCH = 1000
MAX_RETRIES = 5


def main() -> None:
    settings = VendorSettings()
    print("connecting...", flush=True)
    client = MongoClient(
        settings.mongo_uri,
        serverSelectionTimeoutMS=90000,
        socketTimeoutMS=180000,
    )
    col = client[settings.mongo_db_name][
        settings.vendors_scraped_profiles_collection
    ]
    print(
        "connected; paging status=extracted via status_id_idx "
        f"(page={PAGE})",
        flush=True,
    )

    last_id = None
    page_num = 0
    scanned = 0
    total_modified = 0
    ww_seen = 0

    while True:
        query: dict = {"status": "extracted"}
        if last_id is not None:
            query["_id"] = {"$gt": last_id}

        docs = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                docs = list(
                    col.find(query, {"_id": 1, "page_url": 1})
                    .sort([("_id", ASCENDING)])
                    .limit(PAGE)
                )
                break
            except PyMongoError as exc:
                print(
                    f"find retry {attempt}/{MAX_RETRIES}: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
                time.sleep(min(2**attempt, 30))
                client = MongoClient(
                    settings.mongo_uri,
                    serverSelectionTimeoutMS=90000,
                    socketTimeoutMS=180000,
                )
                col = client[settings.mongo_db_name][
                    settings.vendors_scraped_profiles_collection
                ]
        if docs is None:
            raise SystemExit("find failed after retries")
        if not docs:
            break

        page_num += 1
        scanned += len(docs)
        last_id = docs[-1]["_id"]
        ww_ids = [
            d["_id"]
            for d in docs
            if "weddingwire.com" in (d.get("page_url") or "").lower()
        ]
        ww_seen += len(ww_ids)
        print(
            f"page {page_num}: fetched={len(docs)} weddingwire={len(ww_ids)} "
            f"scanned={scanned} ww_total={ww_seen}",
            flush=True,
        )

        for i in range(0, len(ww_ids), UPDATE_BATCH):
            batch = ww_ids[i : i + UPDATE_BATCH]
            result = None
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    result = col.update_many(
                        {"_id": {"$in": batch}, "status": "extracted"},
                        {"$set": {"status": "scraped"}},
                    )
                    break
                except PyMongoError as exc:
                    print(
                        f"update retry {attempt}/{MAX_RETRIES}: "
                        f"{type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    time.sleep(min(2**attempt, 30))
                    client = MongoClient(
                        settings.mongo_uri,
                        serverSelectionTimeoutMS=90000,
                        socketTimeoutMS=180000,
                    )
                    col = client[settings.mongo_db_name][
                        settings.vendors_scraped_profiles_collection
                    ]
            if result is None:
                raise SystemExit("update failed after retries")
            total_modified += result.modified_count
            print(
                f"  updated matched={result.matched_count} "
                f"modified={result.modified_count} "
                f"total_modified={total_modified}",
                flush=True,
            )

    print(
        f"done pages={page_num} scanned={scanned} "
        f"ww_seen={ww_seen} total_modified={total_modified}",
        flush=True,
    )


if __name__ == "__main__":
    main()

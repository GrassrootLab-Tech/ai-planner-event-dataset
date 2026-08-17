"""One-off: weddingwire extracted -> scraped, one doc at a time."""
from __future__ import annotations

import time

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from vendor_profiles.config import VendorSettings

MAX_RETRIES = 5
QUERY = {
    "status": "extracted",
    # Anchored so page_url unique index can help
    "page_url": {
        "$regex": r"^https://(www\.)?weddingwire\.com",
        "$options": "i",
    },
}


def main() -> None:
    settings = VendorSettings()
    print("connecting...", flush=True)
    client = MongoClient(
        settings.mongo_uri,
        serverSelectionTimeoutMS=90000,
        socketTimeoutMS=120000,
    )
    col = client[settings.mongo_db_name][
        settings.vendors_scraped_profiles_collection
    ]
    print(
        "connected db=",
        settings.mongo_db_name,
        "col=",
        settings.vendors_scraped_profiles_collection,
        flush=True,
    )

    updated = 0
    while True:
        doc = None
        ok = False
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                print(f"find #{updated + 1}...", flush=True)
                doc = col.find_one(QUERY, {"_id": 1, "page_url": 1, "status": 1})
                ok = True
                break
            except PyMongoError as exc:
                print(
                    f"find retry {attempt}/{MAX_RETRIES}: {type(exc).__name__}: {exc}",
                    flush=True,
                )
                time.sleep(min(2**attempt, 30))
                client = MongoClient(
                    settings.mongo_uri,
                    serverSelectionTimeoutMS=90000,
                    socketTimeoutMS=120000,
                )
                col = client[settings.mongo_db_name][
                    settings.vendors_scraped_profiles_collection
                ]
        if not ok:
            raise SystemExit("find failed after retries")
        if doc is None:
            print(f"no more weddingwire extracted docs after {updated} updates", flush=True)
            break

        oid = doc["_id"]
        url = doc.get("page_url")
        print(f"found id={oid} url={url}; updating...", flush=True)

        result = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = col.update_one(
                    {"_id": oid, "status": "extracted"},
                    {"$set": {"status": "scraped"}},
                )
                break
            except PyMongoError as exc:
                print(
                    f"update retry {attempt}/{MAX_RETRIES}: {type(exc).__name__}: {exc}",
                    flush=True,
                )
                time.sleep(min(2**attempt, 30))
                client = MongoClient(
                    settings.mongo_uri,
                    serverSelectionTimeoutMS=90000,
                    socketTimeoutMS=120000,
                )
                col = client[settings.mongo_db_name][
                    settings.vendors_scraped_profiles_collection
                ]
        if result is None:
            raise SystemExit(f"update failed for {oid}")

        updated += 1
        print(
            f"{updated} updated matched={result.matched_count} "
            f"modified={result.modified_count} id={oid} url={url}",
            flush=True,
        )

    print(f"done total_updated={updated}", flush=True)


if __name__ == "__main__":
    main()

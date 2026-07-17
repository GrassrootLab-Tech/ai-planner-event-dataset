"""Clean page_url values in event_scraped_content.

Strips query params (?) and trailing forward/backslashes using
utils.url.clean_page_url.

Default is dry-run (no writes). Pass --apply to update MongoDB.

Does not run against chunks; only event_scraped_content.page_url.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Settings
from utils.url import clean_page_url, extract_website


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Clean event_scraped_content.page_url "
            "(strip ?query and trailing / \\)."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist updates. Without this flag, only report what would change.",
    )
    return parser.parse_args()


def needs_cleaning(page_url: str) -> bool:
    if not page_url:
        return False
    return page_url != clean_page_url(page_url)


def main() -> None:
    args = parse_args()
    settings = Settings()
    client = MongoClient(settings.mongo_uri)
    collection = client[settings.mongo_db_name][
        settings.event_scraped_content_collection
    ]

    try:
        # Candidates: query string or trailing slash/backslash.
        cursor = collection.find(
            {
                "$or": [
                    {"page_url": {"$regex": r"\?"}},
                    {"page_url": {"$regex": r"[/\\]+$"}},
                ]
            },
            {"_id": 1, "page_url": 1, "website": 1},
        )

        would_update = 0
        updated = 0
        skipped_noop = 0
        skipped_conflict = 0
        conflicts: list[tuple[str, str]] = []

        for doc in cursor:
            raw = doc.get("page_url") or ""
            if not isinstance(raw, str) or not needs_cleaning(raw):
                skipped_noop += 1
                continue

            cleaned = clean_page_url(raw)
            if not cleaned:
                print(f"SKIP empty after clean: {raw!r}")
                skipped_noop += 1
                continue

            # Collision: another doc already owns the cleaned URL.
            existing = collection.find_one(
                {"page_url": cleaned, "_id": {"$ne": doc["_id"]}},
                {"_id": 1},
            )
            if existing is not None:
                skipped_conflict += 1
                conflicts.append((raw, cleaned))
                print(f"CONFLICT  {raw}")
                print(f"       -> {cleaned}  (already exists as _id={existing['_id']})")
                continue

            new_website = extract_website(cleaned)
            would_update += 1
            print(f"{'APPLY' if args.apply else 'DRY'}  {raw}")
            print(f"    -> {cleaned}")

            if args.apply:
                result = collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"page_url": cleaned, "website": new_website}},
                )
                if result.modified_count:
                    updated += 1

        print()
        print(f"mode: {'APPLY' if args.apply else 'DRY-RUN'}")
        print(f"would_update / updated: {would_update if not args.apply else updated}")
        print(f"skipped_noop: {skipped_noop}")
        print(f"skipped_conflict: {skipped_conflict}")
        if conflicts:
            print(
                "Note: conflict docs were left unchanged. "
                "Resolve duplicates manually before re-running."
            )
        print(
            "Note: event_scraped_chunks.page_url is not updated by this script."
        )
    finally:
        client.close()


if __name__ == "__main__":
    main()

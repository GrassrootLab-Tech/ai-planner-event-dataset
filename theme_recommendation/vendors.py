"""Look up vendor business_name + slug from MongoDB vendors collection."""

from __future__ import annotations

import re
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

VENDOR_PROFILE_BASE = "https://partyhub-website-dev.vercel.app/pro"
SUGGESTED_VENDORS_URL = (
    "https://partyhub-website-dev.vercel.app/api/v1/vendors/id/{vendor_id}/suggested-vendors"
)


def vendor_profile_url(slug: str) -> str:
    return f"{VENDOR_PROFILE_BASE}/{slug.strip().strip('/')}"


def suggested_vendors_url(vendor_id: str) -> str:
    return SUGGESTED_VENDORS_URL.format(vendor_id=vendor_id)


async def fetch_vendor_id_by_business_name(
    collection: Any,
    business_name: str,
) -> dict[str, str] | None:
    """Return {vendor_id, business_name, slug} for an exact case-insensitive name match."""
    name = business_name.strip()
    if not name:
        return None

    escaped = re.escape(name)
    doc = await collection.find_one(
        {"business_name": {"$regex": f"^{escaped}$", "$options": "i"}},
        {"business_name": 1, "slug": 1},
    )
    if not doc:
        return None

    found_name = str(doc.get("business_name") or "").strip()
    slug = str(doc.get("slug") or "").strip()
    return {
        "vendor_id": str(doc["_id"]),
        "business_name": found_name,
        "slug": slug,
    }


async def fetch_vendors_by_ids(
    collection: Any,
    vendor_ids: list[str],
) -> dict[str, dict[str, str]]:
    """Return map vendor_id_str -> {business_name, slug} for found docs."""
    unique_ids = [vid for vid in dict.fromkeys(vendor_ids) if vid]
    if not unique_ids:
        return {}

    object_ids: list[ObjectId] = []
    id_by_oid: dict[ObjectId, str] = {}
    for vid in unique_ids:
        try:
            oid = ObjectId(vid)
        except (InvalidId, TypeError):
            continue
        object_ids.append(oid)
        id_by_oid[oid] = vid

    if not object_ids:
        return {}

    found: dict[str, dict[str, str]] = {}
    cursor = collection.find(
        {"_id": {"$in": object_ids}},
        {"business_name": 1, "slug": 1},
    )
    async for doc in cursor:
        oid = doc["_id"]
        key = id_by_oid.get(oid, str(oid))
        name = str(doc.get("business_name") or "").strip()
        slug = str(doc.get("slug") or "").strip()
        if name and slug:
            found[key] = {"business_name": name, "slug": slug}
    return found

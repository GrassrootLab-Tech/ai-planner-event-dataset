from __future__ import annotations

from typing import Any
from html import escape

import httpx
import streamlit as st

from config import Settings
from db.mongo import Mongo
from streamlit_ui import run_async
from theme_recommendation.vendors import (
    fetch_vendor_id_by_business_name,
    suggested_vendors_url,
    vendor_profile_url,
)

st.set_page_config(page_title="Other Similar Vendors", layout="wide")
st.title("Other Similar Vendors")
st.markdown(
    """
Enter a vendor **business name**, look up their `vendor_id` in MongoDB,
then fetch similar vendors from the PartyHub suggested-vendors API.
"""
)

business_name = st.text_input(
    "Business name",
    value="",
    placeholder="e.g. Build A Party",
)


def _vendor_image(vendor: dict[str, Any]) -> str | None:
    picture = vendor.get("profile_picture")
    if isinstance(picture, str) and picture.strip():
        return picture.strip()
    portfolio = vendor.get("portfolio_files") or []
    if isinstance(portfolio, list):
        for item in portfolio:
            if not isinstance(item, dict):
                continue
            preview = item.get("preview")
            if isinstance(preview, str) and preview.strip():
                return preview.strip()
    return None


def _format_location(vendor: dict[str, Any]) -> str | None:
    loc = vendor.get("business_location") or {}
    if not isinstance(loc, dict):
        return None
    parts = [
        str(loc.get(key) or "").strip()
        for key in ("city", "state", "zip_code")
        if str(loc.get(key) or "").strip()
    ]
    return ", ".join(parts) if parts else None


def _format_prices(vendor: dict[str, Any]) -> str | None:
    prices = vendor.get("prices") or []
    if not isinstance(prices, list) or not prices:
        return None
    lines: list[str] = []
    for price in prices:
        if not isinstance(price, dict):
            continue
        amount = price.get("amount")
        per = str(price.get("per") or "").strip()
        if amount is None:
            continue
        try:
            amount_num = float(amount)
            amount_str = (
                f"${int(amount_num):,}"
                if amount_num == int(amount_num)
                else f"${amount_num:,.2f}"
            )
        except (TypeError, ValueError):
            amount_str = f"${amount}"
        if per:
            lines.append(f"Starting at {amount_str} per {per}")
        else:
            lines.append(f"Starting at {amount_str}")
    return " · ".join(lines) if lines else None


def _subcategory_pills(vendor: dict[str, Any]) -> str:
    categories = vendor.get("categories") or []
    if not isinstance(categories, list):
        return ""
    seen: set[str] = set()
    pills: list[str] = []
    for cat in categories:
        if not isinstance(cat, dict):
            continue
        sub = str(cat.get("sub_category") or "").strip()
        if not sub or sub in seen:
            continue
        seen.add(sub)
        pills.append(
            f'<span class="sv-pill">{escape(sub)}</span>'
        )
    if not pills:
        return ""
    return f'<div class="sv-pills">{"".join(pills)}</div>'


def _render_vendor(vendor: dict[str, Any], index: int) -> None:
    name = str(vendor.get("business_name") or f"Vendor {index}").strip()
    slug = str(vendor.get("slug") or "").strip()
    description = str(vendor.get("description") or "").strip()
    location = _format_location(vendor)
    prices = _format_prices(vendor)
    image_url = _vendor_image(vendor)
    pills_html = _subcategory_pills(vendor)

    label = name
    if location:
        label = f"{name} — {location}"

    with st.expander(label, expanded=index == 1):
        col_img, col_body = st.columns([1, 2], gap="large")
        with col_img:
            if image_url:
                st.image(image_url, use_container_width=True)
            else:
                st.caption("No image available")
        with col_body:
            if slug:
                st.markdown(f"**[{name}]({vendor_profile_url(slug)})**")
            else:
                st.markdown(f"**{name}**")
            if location:
                st.caption(location)
            if prices:
                st.markdown(prices)
            if pills_html:
                st.markdown(pills_html, unsafe_allow_html=True)
            if description:
                st.markdown(description)


async def _load_suggestions(name: str) -> tuple[dict[str, str], list[dict[str, Any]]]:
    settings = Settings()
    mongo = Mongo(settings.mongo_uri, settings.vendors_mongo_db_name)
    await mongo.connect()
    try:
        vendor = await fetch_vendor_id_by_business_name(
            mongo.db[settings.vendors_collection],
            name,
        )
    finally:
        await mongo.disconnect()

    if not vendor:
        raise ValueError(f'No vendor found with business name "{name}"')

    url = suggested_vendors_url(vendor["vendor_id"])
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()

    if not payload.get("success"):
        raise ValueError("Suggested vendors API returned success=false")

    results = (payload.get("data") or {}).get("results") or []
    if not isinstance(results, list):
        raise ValueError("Unexpected suggested vendors response shape")

    return vendor, [r for r in results if isinstance(r, dict)]


st.markdown(
    """
    <style>
    .sv-pills { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.5rem 0 0.75rem; }
    .sv-pill {
        display: inline-block;
        padding: 0.2rem 0.65rem;
        border-radius: 999px;
        background: #eef2ff;
        color: #3730a3;
        font-size: 0.8rem;
        line-height: 1.4;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if st.button("Find similar vendors", type="primary"):
    query = business_name.strip()
    if not query:
        st.warning("Business name is required.")
        st.stop()

    try:
        with st.spinner("Looking up vendor and fetching suggestions…"):
            source, suggestions = run_async(_load_suggestions(query))
    except httpx.HTTPError as exc:
        st.error(f"Suggested vendors API request failed: {exc}")
        st.stop()
    except Exception as exc:
        st.error(str(exc))
        st.stop()

    source_label = source["business_name"]
    if source.get("slug"):
        source_label = f"[{source_label}]({vendor_profile_url(source['slug'])})"
    st.success(
        f"Found **{len(suggestions)}** similar vendors for {source_label} "
        f"(`{source['vendor_id']}`)"
    )

    if not suggestions:
        st.info("No suggested vendors returned.")
    else:
        for i, vendor in enumerate(suggestions, start=1):
            _render_vendor(vendor, i)

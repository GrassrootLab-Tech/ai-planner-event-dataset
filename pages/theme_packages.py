from __future__ import annotations

from datetime import date, time
from typing import Any

import streamlit as st

from clients.gemini_embedding_client import GeminiEmbeddingClient
from clients.openai_embedding_client import OpenAIEmbeddingClient
from config import Settings
from db.mongo import Mongo
from streamlit_ui import extract_chunk_tags, render_claude_cost, run_async
from theme_packages.constants import (
    BUDGET_OPTIONS,
    SERVICE_TYPE_OPTIONS,
    ThemeFormInput,
)
from theme_packages.haiku import ThemePackage
from theme_packages.service import (
    ThemePackageResult,
    run_attach_package_images,
    run_facet_retrieve,
    run_stage1_filters,
    run_stage2_packages,
)
from theme_recommendation.vendors import vendor_profile_url

DEFAULT_SERVICE_TYPES = [
    "Food & Beverage",
    "Entertainment (Musical)",
    "Photography & Videography",
]
DEFAULT_BUDGET = "$5,000 – $8,000"

st.set_page_config(page_title="Theme Packages", layout="wide")
st.title("Theme Packages POC")
st.markdown(
    """
- Fill the event form (**event_type** required; empty fields skip their tags)
- Haiku Stage 1 maps answers → `input_filters`
- **11 facet Pinecone queries** (async, parallel, `top_k=3`) with hardcoded filters
  plus Stage-1 tags in each facet `$or`
- Haiku writes **3 theme packages**, each with a catchy theme name (core vibe)
  plus **6–7** idea strings (~10–15 words)
- Embed each idea with **Gemini** → parallel async `image-index-v2` queries
- Drop ideas whose image URL fails the 1-byte reachability check
- Look up `vendor_id` in MongoDB `vendors` → show business name under the image
- UI updates after each pipeline step
"""
)

col1, col2 = st.columns(2)
with col1:
    event_type = st.text_input("Event type *", value="birthday")
    celebratee = st.text_input("Celebratee", value="friend")
    location = st.text_input("Location", value="Denver, CO, USA")
    event_date = st.date_input("Date", value=date(2025, 8, 15))
    start_time = st.time_input("Start time", value=time(17, 0))
    end_time = st.time_input("End time", value=time(22, 0))
with col2:
    attendees_raw = st.text_input(
        "Attendees",
        value="family, friends, colleagues",
        help="Comma-separated list",
    )
    attendees_age_range = st.text_input(
        "Attendees age range",
        value="25–65",
    )
    guest_count = st.text_input("Guest count", value="80")
    service_type = st.multiselect(
        "Service type",
        list(SERVICE_TYPE_OPTIONS),
        default=DEFAULT_SERVICE_TYPES,
    )
    budget = st.selectbox(
        "Budget",
        options=list(BUDGET_OPTIONS),
        index=list(BUDGET_OPTIONS).index(DEFAULT_BUDGET),
    )


def _render_stage1(
    *,
    input_filters: dict[str, Any],
    pinecone_query: str,
    facet_queries: dict[str, str],
    facet_filters: dict[str, Any],
) -> None:
    with st.expander("Stage 1 LLM output", expanded=False):
        st.json(
            {
                "input_filters": input_filters,
                "pinecone_query": pinecone_query,
            }
        )
    with st.expander("Facet queries", expanded=False):
        st.json(facet_queries)
    with st.expander("Facet Pinecone filters", expanded=False):
        st.json(facet_filters)


def _render_text_hits(chunk_matches: list[dict[str, Any]]) -> None:
    with st.expander(f"Text hits ({len(chunk_matches)})", expanded=False):
        if not chunk_matches:
            st.info("No text hits.")
            return
        for index, match in enumerate(chunk_matches, start=1):
            heading = str(
                match.get("metadata", {}).get("parent_section_heading") or ""
            ).strip()
            facet = match.get("facet") or "?"
            label = heading or match.get("id") or f"hit {index}"
            with st.expander(
                f"{index}. [{facet}] {label} · score={match['score']:.4f}",
                expanded=False,
            ):
                st.markdown(
                    f'<p style="font-size:1.1rem"><b>id:</b> '
                    f'<code>{match["id"]}</code></p>',
                    unsafe_allow_html=True,
                )
                if match.get("page_url"):
                    st.markdown(
                        f'<p style="font-size:1.1rem"><b>Source:</b> '
                        f'<a href="{match["page_url"]}">{match["page_url"]}</a></p>',
                        unsafe_allow_html=True,
                    )
                st.markdown(
                    f'<p style="font-size:1.15rem">'
                    f'{match.get("chunk") or "_(empty)_"}</p>',
                    unsafe_allow_html=True,
                )
                tags = extract_chunk_tags(match.get("metadata") or {})
                with st.expander(f"Tags ({len(tags)})", expanded=False):
                    if tags:
                        st.json(tags)
                    else:
                        st.caption("No tags in metadata.")


def _render_stage2(stage2_packages: list[ThemePackage]) -> None:
    with st.expander("Stage 2 LLM output", expanded=False):
        st.json(
            [
                {"name": pkg.name, "ideas": list(pkg.ideas)}
                for pkg in stage2_packages
            ]
        )


def _render_packages(packages: list[ThemePackageResult]) -> None:
    st.markdown("### Theme packages")
    st.caption("These help you imagine how your event will look like.")
    st.markdown(
        """
        <style>
        div[data-testid="stExpander"] details summary p {
            font-size: 1.2rem !important;
            line-height: 1.4 !important;
        }
        .tp-moodboard {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 12px;
            margin-top: 0.5rem;
        }
        .tp-tile-img {
            border-radius: 12px;
            overflow: hidden;
            aspect-ratio: 1 / 1;
            background: #f0f0f0;
        }
        .tp-tile-img img {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }
        .tp-tile-text {
            border-radius: 12px;
            background: #f3f3f3;
            padding: 1rem;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
            min-height: 140px;
            font-size: 0.95rem;
            line-height: 1.4;
            color: #222;
        }
        .tp-vendor {
            font-size: 0.85rem;
            margin-top: 0.35rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    if not any(pkg.ideas for pkg in packages):
        st.info("No packages with accessible images.")
        return
    for pkg_index, package in enumerate(packages, start=1):
        label = package.name.strip() or f"Theme Package {pkg_index}"
        with st.expander(label, expanded=False):
            if not package.ideas:
                st.caption("No ideas with accessible images in this package.")
                continue
            tiles_html: list[str] = ['<div class="tp-moodboard">']
            for idea in package.ideas:
                if idea.image_url:
                    vendor_html = ""
                    if idea.business_name and idea.slug:
                        profile_url = vendor_profile_url(idea.slug)
                        vendor_html = (
                            f'<div class="tp-vendor">'
                            f'<a href="{profile_url}" target="_blank">'
                            f"{idea.business_name}</a></div>"
                        )
                    tiles_html.append(
                        f'<div><div class="tp-tile-img">'
                        f'<img src="{idea.image_url}" /></div>'
                        f"{vendor_html}</div>"
                    )
                tiles_html.append(f'<div class="tp-tile-text">{idea.idea}</div>')
            tiles_html.append("</div>")
            st.markdown("".join(tiles_html), unsafe_allow_html=True)


if st.button("Generate theme packages", type="primary"):
    if not event_type.strip():
        st.warning("Event type is required.")
        st.stop()

    attendees = [part.strip() for part in attendees_raw.split(",") if part.strip()]
    form = ThemeFormInput(
        event_type=event_type.strip(),
        celebratee=celebratee.strip() or None,
        location=location.strip() or None,
        event_date=event_date,
        start_time=start_time if isinstance(start_time, time) else None,
        end_time=end_time if isinstance(end_time, time) else None,
        attendees=attendees,
        attendees_age_range=attendees_age_range.strip() or None,
        guest_count=guest_count.strip() or None,
        service_type=list(service_type),
        budget=budget.strip() or None,
    )

    try:
        settings = Settings()
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required")
        if not settings.pinecone_api_key:
            raise ValueError("PINECONE_API_KEY is required")
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required")
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required for image-index-v2 embeddings")

        embedder = OpenAIEmbeddingClient(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
        )
        image_embedder = GeminiEmbeddingClient(
            api_key=settings.gemini_api_key,
            model=settings.gemini_embedding_model,
        )

        # --- Step 1: Stage 1 LLM ---
        with st.spinner("Step 1/4: Stage 1 LLM (input filters)..."):
            stage1_step = run_async(
                run_stage1_filters(
                    form=form,
                    anthropic_api_key=settings.anthropic_api_key,
                    anthropic_model=settings.anthropic_query_tagging_model,
                )
            )
        _render_stage1(
            input_filters=stage1_step.stage1.input_filters,
            pinecone_query=stage1_step.stage1.pinecone_query,
            facet_queries=stage1_step.facet_queries,
            facet_filters=stage1_step.facet_filters,
        )

        # --- Step 2: 11 facet Pinecone queries ---
        with st.spinner("Step 2/4: Retrieving text hits (11 facet queries)..."):
            facet_step = run_async(
                run_facet_retrieve(
                    input_filters=stage1_step.stage1.input_filters,
                    embedder=embedder,
                    pinecone_api_key=settings.pinecone_api_key,
                    chunk_index_name=settings.pinecone_index_name,
                )
            )
        _render_text_hits(facet_step.chunk_matches)

        # --- Step 3: Stage 2 LLM ---
        with st.spinner("Step 3/4: Stage 2 LLM (theme packages)..."):
            stage2_step = run_async(
                run_stage2_packages(
                    form_summary=stage1_step.form_summary,
                    chunk_texts=facet_step.chunk_texts,
                    anthropic_api_key=settings.anthropic_api_key,
                    anthropic_model=settings.anthropic_query_tagging_model,
                )
            )
        _render_stage2(stage2_step.packages)

        # --- Step 4: images + vendors ---
        with st.spinner("Step 4/4: Embedding ideas, fetching images, vendors..."):

            async def _images() -> list[ThemePackageResult]:
                mongo = Mongo(settings.mongo_uri, settings.vendors_mongo_db_name)
                await mongo.connect()
                try:
                    return await run_attach_package_images(
                        stage2_packages=stage2_step.packages,
                        image_embedder=image_embedder,
                        pinecone_api_key=settings.pinecone_api_key,
                        image_index_name=settings.pinecone_image_index_name,
                        vendors_collection=mongo.db[settings.vendors_collection],
                    )
                finally:
                    await mongo.disconnect()

            packages = run_async(_images())
        _render_packages(packages)

        render_claude_cost(
            settings.anthropic_query_tagging_model,
            stages={
                "Stage 1 (filters)": stage1_step.usage,
                "Stage 2 (packages)": stage2_step.usage,
            },
        )

    except Exception as exc:
        st.error(str(exc))

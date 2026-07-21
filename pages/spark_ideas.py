from __future__ import annotations

from datetime import date, time

import streamlit as st

from clients.gemini_embedding_client import GeminiEmbeddingClient
from clients.openai_embedding_client import OpenAIEmbeddingClient
from clients.pinecone_client import PineconeClient
from config import Settings
from db.mongo import Mongo
from spark_ideas.constants import (
    BUDGET_OPTIONS,
    SERVICE_TYPE_OPTIONS,
    ThemeFormInput,
)
from spark_ideas.service import recommend_spark_ideas
from streamlit_ui import extract_chunk_tags, run_async
from theme_recommendation.vendors import vendor_profile_url

DEFAULT_SERVICE_TYPES = [
    "Food & Beverage",
    "Entertainment (Musical)",
    "Photography & Videography",
]
DEFAULT_BUDGET = "$5,000 – $8,000"

st.set_page_config(page_title="Spark Ideas", layout="wide")
st.title("Spark Ideas POC")
st.markdown(
    """
- Fill the event form (**event_type** required)
- **No Stage-1 LLM** — fixed embedding query from `event_type` (+ celebratee if set)
- Pinecone filter: **AND** `event_type` + **OR** of these three spark signals:
  - **statement_piece** — field `$exists` (sentinels / empty lists are not stored)
  - **photo_moment_flag** — `$eq` true (strong photo opportunity)
  - **personalization_element** — field `$exists` (sentinels / empty lists are not stored)
- Search `ai-planner-dataset` for top **7** matching chunks
- Haiku writes **7** numbered conversational spark ideas (inspired by the chunks)
- Embed each idea with **Gemini** → query `image-index-v2`
- Keep only ideas whose image URL is reachable (1-byte check)
- Look up `vendor_id` in MongoDB `vendors` → show business name under the image
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
    top_k = st.number_input("top_k", min_value=1, max_value=20, value=7, step=1)

if st.button("Spark ideas", type="primary"):
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
        chunk_index = PineconeClient(
            api_key=settings.pinecone_api_key,
            index_name=settings.pinecone_index_name,
        )
        image_index = PineconeClient(
            api_key=settings.pinecone_api_key,
            index_name=settings.pinecone_image_index_name,
        )

        with st.spinner("Retrieving spark chunks, synthesizing ideas, fetching images..."):

            async def _run():
                mongo = Mongo(settings.mongo_uri, settings.vendors_mongo_db_name)
                await mongo.connect()
                try:
                    return await recommend_spark_ideas(
                        form=form,
                        embedder=embedder,
                        image_embedder=image_embedder,
                        chunk_index=chunk_index,
                        image_index=image_index,
                        anthropic_api_key=settings.anthropic_api_key,
                        anthropic_model=settings.anthropic_query_tagging_model,
                        top_k=int(top_k),
                        vendors_collection=mongo.db[settings.vendors_collection],
                    )
                finally:
                    await mongo.disconnect()

            outcome = run_async(_run())

        with st.expander("Embedding query", expanded=False):
            st.write(outcome.pinecone_query)
        with st.expander("Pinecone filters", expanded=False):
            st.json(outcome.pinecone_filter)

        st.markdown("### Text hits")
        if not outcome.chunk_matches:
            st.info("No text hits.")
        else:
            for index, match in enumerate(outcome.chunk_matches, start=1):
                heading = str(
                    match.get("metadata", {}).get("parent_section_heading") or ""
                ).strip()
                label = heading or match.get("id") or f"hit {index}"
                with st.expander(
                    f"{index}. {label} · score={match['score']:.4f}",
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

        with st.expander("Haiku spark ideas", expanded=False):
            st.json([{"idea": i.idea} for i in outcome.stage2_ideas])

        st.markdown("### Spark ideas")
        st.markdown(
            """
            <style>
            div[data-testid="stExpander"] details summary p {
                font-size: 1.2rem !important;
                line-height: 1.4 !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        if not outcome.ideas:
            st.info("No spark ideas with accessible images.")
        else:
            for index, item in enumerate(outcome.ideas, start=1):
                with st.expander(f"Idea {index}", expanded=True):
                    st.markdown(
                        f'<p style="font-size:1.2rem;line-height:1.4;margin:0 0 0.75rem 0;">'
                        f"{item.idea}</p>",
                        unsafe_allow_html=True,
                    )
                    if item.image_url:
                        st.markdown(
                            f'<div style="width:200px;height:200px;overflow:hidden;'
                            f'border-radius:8px;">'
                            f'<img src="{item.image_url}" '
                            f'style="width:100%;height:100%;object-fit:cover;" />'
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                        if item.business_name and item.slug:
                            profile_url = vendor_profile_url(item.slug)
                            st.markdown(
                                f'<p style="font-size:1.1rem;margin-top:0.5rem;">'
                                f'<a href="{profile_url}" target="_blank">'
                                f"{item.business_name}</a></p>",
                                unsafe_allow_html=True,
                            )

    except Exception as exc:
        st.error(str(exc))

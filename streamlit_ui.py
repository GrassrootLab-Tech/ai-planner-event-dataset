"""Shared Streamlit helpers for retrieval UIs. No retrieval logic here."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

import streamlit as st

from retrieval import RetrievalResult
from tags.order import METADATA_TAG_ORDER, SCALAR_LIST_VALUES

T = TypeVar("T")

CONTENT_METADATA_KEYS = frozenset({
    "chunk",
    "page_url",
    "parent_section_heading",
    "scraped_at",
    "embedding_model",
})


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def extract_chunk_tags(metadata: dict[str, Any]) -> dict[str, Any]:
    tags: dict[str, Any] = {}
    for key in METADATA_TAG_ORDER:
        if key not in metadata or key in CONTENT_METADATA_KEYS:
            continue
        value = metadata[key]
        if value is None or value == "":
            continue
        if isinstance(value, str) and value in SCALAR_LIST_VALUES:
            continue
        if isinstance(value, list) and (
            not value or all(item in SCALAR_LIST_VALUES for item in value)
        ):
            continue
        tags[key] = value

    for key, value in metadata.items():
        if key in CONTENT_METADATA_KEYS or key in tags:
            continue
        if value is None or value == "":
            continue
        tags[key] = value

    return tags


def render_result_card(
    index: int,
    result: RetrievalResult,
    *,
    show_hybrid_scores: bool = False,
) -> None:
    if show_hybrid_scores:
        score_line = (
            f"combined={result.combined_score:.4f} · "
            f"content={result.content_similarity:.4f} · "
            f"tag={result.tag_similarity:.4f}"
        )
    else:
        score_line = f"score={result.content_similarity:.4f}"

    tags = extract_chunk_tags(result.metadata)

    with st.container(border=True):
        st.markdown(f"**[{index}]** {score_line}")
        st.caption(f"id: `{result.id}`")
        if result.page_url:
            st.markdown(f"[Source]({result.page_url})")
        st.markdown(result.chunk or "_(empty chunk)_")
        with st.expander(f"Tags ({len(tags)})", expanded=False):
            if tags:
                st.json(tags)
            else:
                st.caption("No tags in metadata.")


def render_answer(answer: str) -> None:
    st.subheader("Haiku Answer")
    st.markdown(answer)

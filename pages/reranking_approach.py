import streamlit as st

from answer_synthesis import synthesize_answer
from clients.openai_embedding_client import OpenAIEmbeddingClient
from clients.pinecone_client import PineconeClient
from config import Settings
from retrieval import Retriever
from streamlit_ui import render_answer, render_result_card, run_async

st.set_page_config(page_title="Reranking Approach", layout="wide")
st.title("Reranking Approach")
st.markdown(
    """
- Embeds your query and retrieves a candidate pool (no metadata filter)
- Scores each candidate’s tags against the query (priority-weighted)
- Combines **60% content + 40% tag** similarity
- Re-ranks and returns the top results
- Haiku writes a grounded conversational answer from the retrieved sources
"""
)

query = st.text_area(
    "Query",
    value=(
        "I'm planning my daughter's birthday party and already have the venue, cake, "
        "and decorations sorted. Looking for some unique or fun ideas to make the day "
        "feel extra special and memorable — something beyond the usual games and activities."
    ),
    height=120,
)
col1, col2 = st.columns(2)
with col1:
    top_k = st.number_input("top_k", min_value=1, max_value=50, value=5, step=1)
with col2:
    candidate_pool = st.number_input(
        "candidate_pool",
        min_value=1,
        max_value=500,
        value=100,
        step=10,
    )
run_final_llm = st.checkbox("Run final LLM generation", value=True)

if st.button("Search", type="primary"):
    if not query.strip():
        st.warning("Enter a query first.")
        st.stop()

    try:
        settings = Settings()
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required")
        if not settings.pinecone_api_key:
            raise ValueError("PINECONE_API_KEY is required")
        if run_final_llm and not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for final LLM generation")

        embedder = OpenAIEmbeddingClient(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
        )
        chunk_index = PineconeClient(
            api_key=settings.pinecone_api_key,
            index_name=settings.pinecone_index_name,
        )
        tags_index = PineconeClient(
            api_key=settings.pinecone_api_key,
            index_name=settings.pinecone_tags_index_name,
        )
        retriever = Retriever(embedder, chunk_index, tags_index)

        query_text = query.strip()
        spinner_label = (
            "Searching and generating answer..."
            if run_final_llm
            else "Searching and reranking..."
        )
        with st.spinner(spinner_label):
            results = run_async(
                retriever.retrieve(
                    query_text,
                    candidate_pool=int(candidate_pool),
                    top_k=int(top_k),
                )
            )
            answer = None
            if run_final_llm:
                answer = run_async(
                    synthesize_answer(
                        api_key=settings.anthropic_api_key or "",
                        model=settings.anthropic_query_tagging_model,
                        query=query_text,
                        results=results,
                    )
                )

        st.subheader(f"Results ({len(results)})")
        if not results:
            st.info("No matches.")
        for index, result in enumerate(results, start=1):
            render_result_card(index, result, show_hybrid_scores=True)

        if answer is not None:
            render_answer(answer)

    except Exception as exc:
        st.error(str(exc))

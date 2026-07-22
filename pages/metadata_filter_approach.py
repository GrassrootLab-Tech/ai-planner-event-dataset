import streamlit as st

from answer_synthesis import synthesize_answer
from clients.openai_embedding_client import OpenAIEmbeddingClient
from clients.pinecone_client import PineconeClient
from config import Settings
from retrieval_metadata_filter import MetadataFilterRetriever
from streamlit_ui import render_answer, render_claude_cost, render_result_card, run_async
from utils.pipeline_cost import TokenUsage

st.set_page_config(page_title="Metadata Filter Approach", layout="wide")
st.title("Metadata Filter Approach")
st.markdown(
    """
- Haiku extracts **must_have** (AND) and **good_to_have** (OR) tags from your query
- Builds a Pinecone metadata filter from those tags
- Embeds the query and searches only filtered chunks
- Ranks by vector similarity
- Haiku writes a grounded conversational answer from the retrieved sources
"""
)

query = st.text_area(
    "Query",
    value=(
        "I am throwing anniversary party for my spouse , recommend some good theme ideas"
    ),
    height=120,
)
top_k = st.number_input("top_k", min_value=1, max_value=50, value=5, step=1)
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
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required")

        embedder = OpenAIEmbeddingClient(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
        )
        chunk_index = PineconeClient(
            api_key=settings.pinecone_api_key,
            index_name=settings.pinecone_index_name,
        )
        retriever = MetadataFilterRetriever(
            embedder,
            chunk_index,
            anthropic_api_key=settings.anthropic_api_key,
            anthropic_model=settings.anthropic_query_tagging_model,
        )

        query_text = query.strip()
        spinner_label = (
            "Searching and generating answer..."
            if run_final_llm
            else "Inferring tags and searching..."
        )
        with st.spinner(spinner_label):
            outcome = run_async(retriever.retrieve(query_text, top_k=int(top_k)))
            answer = None
            answer_usage = TokenUsage()
            if run_final_llm:
                answer, answer_usage = run_async(
                    synthesize_answer(
                        api_key=settings.anthropic_api_key,
                        model=settings.anthropic_query_tagging_model,
                        query=query_text,
                        results=outcome.results,
                    )
                )

        cost_stages = {"Stage 1 (query tags)": outcome.usage}
        if run_final_llm:
            cost_stages["Stage 2 (answer)"] = answer_usage
        render_claude_cost(
            settings.anthropic_query_tagging_model,
            stages=cost_stages,
        )

        with st.expander("must_have", expanded=False):
            st.json(outcome.inference.must_have)
        with st.expander("good_to_have", expanded=False):
            st.json(outcome.inference.good_to_have)
        with st.expander("pinecone_filter", expanded=False):
            st.json(outcome.filter)

        st.subheader(f"Results ({len(outcome.results)})")
        if not outcome.results:
            st.info("No matches.")
        for index, result in enumerate(outcome.results, start=1):
            render_result_card(index, result, show_hybrid_scores=False)

        if answer is not None:
            render_answer(answer)

    except Exception as exc:
        st.error(str(exc))

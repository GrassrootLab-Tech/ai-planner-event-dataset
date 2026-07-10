import streamlit as st

st.set_page_config(
    page_title="AI Planner Retrieval",
    layout="wide",
)

st.title("AI Planner Retrieval")
st.write(
    "Compare two ways to retrieve party-planning idea chunks. "
    "Pick an approach from the sidebar."
)

st.subheader("Metadata filter approach")
st.markdown(
    """
- Claude Haiku reads your query and extracts structured tags.
- Hard constraints go into **must_have** (AND filters).
- Soft preferences go into **good_to_have** (OR filters).
- Those tags become a Pinecone metadata filter.
- Your query is embedded and searched **only among chunks that match the filter**.
- Returns the top matches by vector similarity (default top 5).
- Haiku writes a grounded conversational answer from the retrieved sources.
- Best when you want results constrained to event type, age, theme, etc.
"""
)

st.subheader("Reranking approach")
st.markdown(
    """
- Your query is embedded and searched against the full chunk index (no metadata filter).
- Pulls a larger candidate pool first (default top 100 by vector score).
- For each candidate, compares the query to that chunk’s tags using pre-indexed tag embeddings.
- Tag matches are weighted by priority: critical > important > good-to-have.
- Final score blends **60% content similarity + 40% tag similarity**.
- Re-ranks the pool and returns the top results (default top 5).
- Haiku writes a grounded conversational answer from the retrieved sources.
- Best when you want broader recall, then relevance refined by tags.
"""
)

st.info("Open **metadata_filter_approach** or **reranking_approach** from the sidebar to try either path.")

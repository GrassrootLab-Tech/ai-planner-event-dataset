import streamlit as st

st.set_page_config(
    page_title="AI Planner Retrieval",
    layout="wide",
)

st.title("AI Planner Retrieval")
st.write(
    "Compare two ways to retrieve party-planning idea chunks, "
    "or try the theme recommendation POC. "
    "Pick an approach from the sidebar."
)

st.subheader("Theme recommendation POC")
st.markdown(
    """
- Fill the event form (**event_type** required; empty fields skip their tags)
- Haiku maps answers → filter tags + a short search query
- Pinecone filter: **AND** (`content_category`, `idea_granularity`, `event_type`) + **OR** (tags inferred from user input ,only a limited set of tags are used because input fields are also limited)
- Search `ai-planner-dataset` for matching theme chunks
- Haiku writes up to **6** themes as `title : description`
- Embed each theme with **Gemini** → query `image-index-v2`
- Return up to **6** themes with images
- Find the associated vendor in the mongodb related to the image
"""
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

st.info(
    "Open **metadata_filter_approach**, **reranking_approach**, or "
    "**theme_recommendation** from the sidebar."
)

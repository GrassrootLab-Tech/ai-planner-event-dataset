# AI Planner Dataset Experiment

Pipeline to scrape event/party planning pages, chunk them, classify usability, tag with AI, and embed into Pinecone for retrieval experiments.

## Pipeline

1. **Scrape** — HasData for normal pages; Reddit OAuth API for post URLs
2. **Chunk** — heading-based markdown chunks, or Reddit post/comment chunks
3. **Classify** — OpenAI usability filter
4. **Tag** — Anthropic metadata tags
5. **Embed** — OpenAI embeddings → Pinecone

Status progresses: `scraped` → `chunked` → `usability_classification` → `ai_tagged` → `embedded`.

Reddit posts store structured `reddit_data` (top 60 comments by score, ≤3 first-level replies each). Other pages store `raw_html` + `markdown`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_md
cp .env.example .env   # fill in keys
```

Requires MongoDB locally (or update `MONGO_URI`). Reddit keys are only needed for Reddit URLs. The spaCy model `en_core_web_md` is required for the anonymization stage.

## Usage

```bash
# Full pipeline for one URL
python main.py run-all "https://example.com/article"

# Individual steps
python main.py scrape "<url>"
python main.py chunk "<url>"
python main.py classify "<url>"
python main.py tag "<url>"
python main.py anonymize "<url>"
python main.py embed "<url>"

# Batch from sample_website.PAGE_URLS
python main.py run-all-sample

# Enable 5-minute prompt caching for AI tagging (reduces cost on repeated runs)
python main.py run-all-sample --cache
python main.py tag "<url>" --cache
python main.py run-all "<url>" --cache

# Populate tag index
python main.py populate-tags
```

## Vendor profile SERP

Queue DataForSEO Google organic tasks for vendor directories (`site:{source} {category} in {city}`), store in Mongo `vendor_data_serp_results`, then poll for results. Depth is 10; existing `search_query` docs are skipped.

```bash
# Interactive: paste one allowlisted source, then city/category index slices (default 0–5)
python scripts/fetch_vendor_serp_results.py

# One-shot poll of status=queued → ok/failed (re-run until empty)
python scripts/poll_vendor_serp_results.py
```

Allowlisted sources, cities, and categories live in `scripts/vendor_profile_sources.py`. Requires `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD`.

## Retrieval UI

```bash
streamlit run app.py
```

## Layout

| Path | Role |
|------|------|
| `main.py` | CLI entrypoint |
| `services/` | Scrape → chunk → classify → tag → embed |
| `scripts/fetch_vendor_serp_results.py` | Queue vendor SERP tasks (interactive) |
| `scripts/poll_vendor_serp_results.py` | Poll queued vendor SERP results |
| `scripts/vendor_profile_sources.py` | Vendor SERP sources / cities / categories |
| `reddit/` | Reddit fetch + chunking |
| `clients/` | HasData, OpenAI, Anthropic, Pinecone |
| `tags/` | Tag definitions + prompts |
| `app.py` / `pages/` | Streamlit retrieval demos |

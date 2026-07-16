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

## Retrieval UI

```bash
streamlit run app.py
```

## Layout

| Path | Role |
|------|------|
| `main.py` | CLI entrypoint |
| `services/` | Scrape → chunk → classify → tag → embed |
| `reddit/` | Reddit fetch + chunking |
| `clients/` | HasData, OpenAI, Anthropic, Pinecone |
| `tags/` | Tag definitions + prompts |
| `app.py` / `pages/` | Streamlit retrieval demos |

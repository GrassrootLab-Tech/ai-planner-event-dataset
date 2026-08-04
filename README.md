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
source .venv/bin/activevate
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

## Vendor profiles (`vendor_profiles/`)

Self-contained package with its own settings (`VendorSettings`) and CLI. Uses research Mongo collections for SERP + staged profiles.

```bash
# Interactive SERP queue (paste source, city/category slices)
python -m vendor_profiles fetch-serp

# Poll queued SERP tasks
python -m vendor_profiles poll-serp

# Stage unprocessed SERP result URLs (even source/city/category mix; default batch 100)
python -m vendor_profiles stage
python -m vendor_profiles stage --batch-size 100 --concurrency 3

# Stage from vendor_profiles/sample_urls.py instead
python -m vendor_profiles stage --run-sample
python -m vendor_profiles stage --run-sample --concurrency 3

# Scrape next batch of staged|failed profiles → html, markdown, scraped_at, status=scraped
python -m vendor_profiles scrape
python -m vendor_profiles scrape --batch-size 100 --concurrency 3

```

Default stage pulls from `vendor_data_serp_results` (`status: ok`), picks URLs whose `results[].status` is missing or not `processed`, stages them, then sets `results[].status` to `processed`. Sample mode uses [`vendor_profiles/sample_urls.py`](vendor_profiles/sample_urls.py) and does not update SERP statuses. Scrape picks FIFO `vendors_scraped_profiles` with `status` in `staged|failed`; success writes `html`/`markdown`/`scraped_at` and `status: scraped`, failures set `status: failed`. Sources/cities/categories: `vendor_profiles/sources.py`. Regex rules: `vendor_profiles/source_rules.py`. After each stage run: `vendor_profiles/output/{timestamp}_{N}_urls_run.txt` (per-URL success/failed + Haiku cost, plus totals). Skip notes: `vendor_profiles/output/vendor_stage_report.txt`.

Env (same `.env`): `HASDATA_API_KEY`, `DATAFORSEO_*`, `ANTHROPIC_API_KEY`, `MONGO_*`, `VENDOR_DATA_SERP_RESULTS_COLLECTION`, `VENDORS_SCRAPED_*`.

## Retrieval UI

```bash
streamlit run app.py
```

## Layout

| Path | Role |
|------|------|
| `main.py` | Event article pipeline CLI |
| `vendor_profiles/` | Vendor SERP + stage + scrape package (`python -m vendor_profiles`) |
| `services/` | Event scrape → chunk → classify → tag → embed |
| `reddit/` | Reddit fetch + chunking |
| `clients/` | Shared HasData, OpenAI, Anthropic, Pinecone |
| `tags/` | Tag definitions + prompts |
| `app.py` / `pages/` | Streamlit retrieval demos |

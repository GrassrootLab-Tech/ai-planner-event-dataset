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

# Stage a random sample from one source (keyword match on source_url; for testing)
python -m vendor_profiles stage --domain partyslate
python -m vendor_profiles stage --domain thebash --batch-size 50

# Stage from vendor_profiles/sample_urls.py instead
python -m vendor_profiles stage --run-sample
python -m vendor_profiles stage --run-sample --concurrency 3

# Dedupe all staged profiles by (host, slug); keep first seen, delete rest
python -m vendor_profiles staging-dedupe
python -m vendor_profiles staging-dedupe --concurrency 1000

# Scrape next batch of staged|failed profiles → html, markdown, scraped_at, status=scraped
python -m vendor_profiles scrape
python -m vendor_profiles scrape --batch-size 100 --concurrency 3

# Extract next batch of scraped profiles → vendors_extracted_profiles (default batch 100)
python -m vendor_profiles extract
python -m vendor_profiles extract --batch-size 100 --concurrency 3

# Extract from vendor_profiles/sample_urls.py instead
python -m vendor_profiles extract --run-sample
python -m vendor_profiles extract --run-sample --concurrency 3
```

Default stage pulls from `vendor_data_serp_results` (`status: ok`), picks URLs whose `results[].status` is missing or not `processed`, stages them, then sets `results[].status` to `processed`. With `--domain <keyword>` (e.g. `partyslate`), it instead takes a random unprocessed batch whose `source_url` contains that keyword. Sample mode uses [`vendor_profiles/sample_urls.py`](vendor_profiles/sample_urls.py) and does not update SERP statuses. Staging-dedupe pages all `vendors_scraped_profiles` with `status: staged` (1000 at a time, no sort) into memory, keys by `(host, slug)` using the same parser `slug_from_url` rules as extract ([`vendor_profiles/dedupe_by_slug.py`](vendor_profiles/dedupe_by_slug.py)), keeps the first URL per key, and deletes all duplicates in DB batches of under 1000 (default concurrency 1000). Scrape picks FIFO `vendors_scraped_profiles` with `status` in `staged|failed`; success writes `html`/`markdown`/`scraped_at` and `status: scraped`, failures set `status: failed`. Extract picks FIFO `vendors_scraped_profiles` with `status: scraped` (or sample URLs with `--run-sample`), uses a rule parser when registered else Haiku over cleaned `markdown`, upserts into `vendors_extracted_profiles` (`page_url`, `extracted_at`, `source`, plus non-null profile fields), sets profile `status: extracted`, and skips URLs already `extracted`. Fragment URLs containing `#` (e.g. WeddingWire section anchors) are marked `extraction_skipped` so they are not re-fetched. Writes `vendor_profiles/output/{timestamp}_extracted_cost.txt` (per-URL tokens/cost + totals). Sources/cities/categories: `vendor_profiles/sources.py`. Regex rules: `vendor_profiles/source_rules.py`. After each stage run: `vendor_profiles/output/{timestamp}_{N}_urls_run.txt` (per-URL success/failed + Haiku cost, plus totals). Skip notes: `vendor_profiles/output/vendor_stage_report.txt`.

Env (same `.env`): `HASDATA_API_KEY`, `DATAFORSEO_*`, `ANTHROPIC_API_KEY`, `MONGO_*`, `VENDOR_DATA_SERP_RESULTS_COLLECTION`, `VENDORS_SCRAPED_*`, `VENDORS_EXTRACTED_PROFILES_COLLECTION`.

## Retrieval UI

```bash
streamlit run app.py
```

## Layout

| Path | Role |
|------|------|
| `main.py` | Event article pipeline CLI |
| `vendor_profiles/` | Vendor SERP + stage + staging-dedupe + scrape + extract (`python -m vendor_profiles`) |
| `services/` | Event scrape → chunk → classify → tag → embed |
| `reddit/` | Reddit fetch + chunking |
| `clients/` | Shared HasData, OpenAI, Anthropic, Pinecone |
| `tags/` | Tag definitions + prompts |
| `app.py` / `pages/` | Streamlit retrieval demos |

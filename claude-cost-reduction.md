# How We Reduced Claude Costs for the AI Event Dataset Project 

Four changes cut our Claude spend for article tagging, anonymization, and query-time generation.

## 1. Prompt caching (system prompt)

The tagging system prompt is large and reused across every article. We mark it with Anthropic’s ephemeral cache (`ttl: 1h`) so it is written once, then cheaply reread on later requests. Cache reads cost ~10% of normal input tokens, which matters most when the same prompt is applied to many chunks.

## 2. Batch processing API

Tagging runs through Anthropic’s Message Batches API instead of live, per-request calls. Batched tokens are billed at half the standard rate. Latency is higher (async queue), but that is fine for offline pipeline work.

## 3. Named-entity replacement with spaCy

Chunk anonymization used to go through Claude. We switched to local spaCy NER (`en_core_web_md`), replacing `PERSON` and `ORG` entities with `[PERSON]` / `[ORG]` placeholders. That step now costs $0 in Claude tokens.

## 4. Using Haiku instead of a larger model

Classification, tagging, and query-time synthesis use **Claude Haiku 4.5** rather than Sonnet. Haiku is cheaper per token (~$1 / $5 per 1M input / output vs ~$3 / $15 for Sonnet) and is accurate enough for structured tagging and short generation tasks.

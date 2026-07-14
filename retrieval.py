from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from math import sqrt
from typing import Any

from num2words import num2words

from clients.openai_embedding_client import OpenAIEmbeddingClient
from clients.pinecone_client import PineconeClient, PineconeMatch
from tags.order import METADATA_TAG_ORDER, SCALAR_LIST_VALUES
from tags.registry import TagRegistry
from utils.logger import log_pretty, logger

TIER_WEIGHTS = {"critical": 1.0, "important": 0.7, "good_to_have": 0.4}
PRIORITY_TO_TIER = {
    "Critical": "critical",
    "Important": "important",
    "Good to have": "good_to_have",
}
CONTENT_METADATA_KEYS = frozenset(
    {
        "chunk",
        "page_url",
        "parent_section_heading",
        "scraped_at",
        "embedding_model",
    }
)
SENTINEL_TAG_VALUES = SCALAR_LIST_VALUES
COMBINED_SCORE_ALPHA = 0.6
TAG_FETCH_BATCH_SIZE = 250
TAG_EMBED_BATCH_SIZE = 250

BOOL_TAG_EMBED_TEXT = {
    ("kid_safe_flag", "true"): "safe for kids",
    ("kid_safe_flag", "false"): "not safe for kids",
    ("photo_moment_flag", "true"): "strong photo opportunity",
    ("photo_moment_flag", "false"): "no strong photo opportunity",
    ("licensed_ip_flag", "false"): "No licensed IP flag present",
}
BOOL_TAG_NAMES = frozenset({"kid_safe_flag", "photo_moment_flag"})
LICENSED_IP_VALUES = (
    "mickey_mouse",
    "frozen",
    "minecraft",
    "bluey",
    "paw_patrol",
    "harry_potter",
    "barbie",
    "pokemon",
    "marvel",
    "star_wars",
    "disney_princess",
    "peppa_pig",
    "cocomelon",
    "sonic_the_hedgehog",
    "super_mario",
    "spiderman",
    "batman",
    "hello_kitty",
    "teenage_mutant_ninja_turtles",
    "sesame_street",
    "transformers",
    "jurassic_park",
    "lilo_and_stitch",
    "moana",
    "toy_story",
    "minions",
    "winnie_the_pooh",
    "spongebob_squarepants",
    "gabbys_dollhouse",
    "squishmallows",
)


@dataclass(frozen=True)
class RetrievalResult:
    id: str
    chunk: str
    page_url: str
    content_similarity: float
    tag_similarity: float
    combined_score: float
    metadata: dict[str, Any]


def ascii_tag_value_slug(tag_value: str) -> str:
    normalized = unicodedata.normalize("NFKD", tag_value)
    return normalized.encode("ascii", "ignore").decode("ascii")


def tag_vector_id(tag_name: str, tag_value: str) -> str:
    return f"{tag_name}:{ascii_tag_value_slug(tag_value)}"


def format_tag_embed_text(tag_name: str, tag_value: str) -> str:
    embed_text = BOOL_TAG_EMBED_TEXT.get((tag_name, tag_value))
    if embed_text is not None:
        return embed_text
    if tag_name == "licensed_ip_flag":
        return " ".join(word.capitalize() for word in tag_value.split("_"))
    return tag_value.replace("_", " ")


def _number_token_to_word_parts(token: str) -> list[str]:
    if re.fullmatch(r"\d+", token):
        number = int(token)
        if 1900 <= number <= 2100:
            return num2words(number, to="year").replace(",", "").split()
        if 100 <= number < 1000:
            hundreds, remainder = divmod(number, 100)
            if remainder == 0:
                return [num2words(hundreds), "hundred"]
            return [num2words(hundreds), num2words(remainder)]
        return num2words(number).replace(",", "").split()

    ordinal_match = re.fullmatch(r"(\d+)(st|nd|rd|th)", token)
    if ordinal_match:
        return (
            num2words(int(ordinal_match.group(1)), to="ordinal")
            .replace(",", "")
            .split()
        )

    return [token.replace("_", " ")]


def _value_tokens_to_words(tag_value: str) -> list[str]:
    tokens = ascii_tag_value_slug(tag_value).split("_")
    words: list[str] = []
    index = 0

    while index < len(tokens):
        token = tokens[index]

        if token.isdigit() and index + 1 < len(tokens) and tokens[index + 1].isdigit():
            words.extend(_number_token_to_word_parts(token))
            words.append("to")
            words.extend(_number_token_to_word_parts(tokens[index + 1]))
            index += 2
            continue

        if token.isdigit() and index + 1 < len(tokens) and tokens[index + 1] == "plus":
            words.extend(_number_token_to_word_parts(token))
            words.append("plus")
            index += 2
            continue

        if token in {"under", "over", "and", "plus", "to"}:
            words.append(token)
        elif token.isdigit() or re.fullmatch(r"\d+(st|nd|rd|th)", token):
            words.extend(_number_token_to_word_parts(token))
        else:
            words.append(token.replace("_", " "))

        index += 1

    return words


def _tag_name_label_words(tag_name: str) -> list[str]:
    skip = {"flag", "the", "of", "for", "and"}
    return [part for part in tag_name.split("_") if part not in skip]


def format_tag_index_embed_phrase(tag_name: str, tag_value: str) -> str:
    """Build a 3-4 word phrase for ai-planner-tags index population only."""
    bool_text = BOOL_TAG_EMBED_TEXT.get((tag_name, tag_value))
    if bool_text is not None:
        return bool_text

    if tag_name == "licensed_ip_flag" and tag_value != "false":
        ip_label = " ".join(word.capitalize() for word in tag_value.split("_"))
        return " ".join([ip_label, "licensed", "character"][:4])

    value_words = _value_tokens_to_words(tag_value)
    label_words = _tag_name_label_words(tag_name)
    phrase_words = value_words + label_words

    if len(phrase_words) > 4 and "to" in value_words:
        to_index = value_words.index("to")
        if to_index >= 1 and to_index + 1 < len(value_words):
            range_words = value_words[to_index - 1 : to_index + 2]
            unit_words: list[str] = []
            unit_index = to_index + 2
            if unit_index < len(value_words):
                unit_words = [value_words[unit_index]]
            phrase_words = range_words + unit_words + label_words

    return " ".join(phrase_words[:4])


def priority_to_tier(priority: str) -> str:
    return PRIORITY_TO_TIER[priority]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sqrt(sum(x * x for x in a))
    norm_b = sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _flatten_tag_values(tag_name: str, value: Any) -> list[str]:
    if tag_name == "licensed_ip_flag":
        if value is False or value == "" or value == "false":
            return ["false"]
        if value is True:
            return ["false"]
        if isinstance(value, str):
            if value == "false":
                return ["false"]
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return ["false"]
            if parsed is False:
                return ["false"]
            if isinstance(parsed, dict) and "ip_names" in parsed:
                ip_names = [
                    ip
                    for ip in parsed["ip_names"]
                    if isinstance(ip, str) and ip and ip not in SENTINEL_TAG_VALUES
                ]
                return ip_names if ip_names else ["false"]
            return ["false"]
        if isinstance(value, dict) and "ip_names" in value:
            ip_names = [
                ip
                for ip in value["ip_names"]
                if isinstance(ip, str) and ip and ip not in SENTINEL_TAG_VALUES
            ]
            return ip_names if ip_names else ["false"]
        if isinstance(value, list):
            ip_names = [
                ip
                for ip in value
                if isinstance(ip, str) and ip and ip not in SENTINEL_TAG_VALUES
            ]
            return ip_names if ip_names else ["false"]
        return ["false"]

    if tag_name in BOOL_TAG_NAMES:
        if isinstance(value, bool):
            return ["true" if value else "false"]
        if isinstance(value, str) and value in {"true", "false"}:
            return [value]
        return []

    if isinstance(value, bool):
        return []

    if isinstance(value, str):
        if not value or value in SENTINEL_TAG_VALUES:
            return []
        return [value]

    if isinstance(value, list):
        return [
            item
            for item in value
            if isinstance(item, str) and item and item not in SENTINEL_TAG_VALUES
        ]

    return []


def build_tags_by_tier(
    metadata: dict[str, Any],
    tag_registry: TagRegistry,
) -> dict[str, list[str]]:
    tags_by_tier: dict[str, list[str]] = {
        "critical": [],
        "important": [],
        "good_to_have": [],
    }

    for tag_name in METADATA_TAG_ORDER:
        if tag_name not in metadata:
            continue

        tag_def = tag_registry.get(tag_name)
        tier = priority_to_tier(tag_def.priority)

        for tag_value in _flatten_tag_values(tag_name, metadata[tag_name]):
            tags_by_tier[tier].append(tag_vector_id(tag_name, tag_value))

    return tags_by_tier


def tag_relevance_score(
    candidate: dict[str, Any],
    query_vector: list[float],
    tag_vocab_embeddings: dict[str, list[float]],
    *,
    top_k: int = 3,
) -> float:
    weighted_scores: list[float] = []

    for tier, tags in candidate["tags_by_tier"].items():
        weight = TIER_WEIGHTS[tier]
        for tag_key in tags:
            tag_vec = tag_vocab_embeddings.get(tag_key)
            if tag_vec is not None:
                sim = cosine_similarity(query_vector, tag_vec)
                weighted_scores.append(sim * weight)

    if not weighted_scores:
        return 0.0

    top_scores = sorted(weighted_scores, reverse=True)[:top_k]
    return sum(top_scores) / len(top_scores)


def combined_score(
    candidate: dict[str, Any], *, alpha: float = COMBINED_SCORE_ALPHA
) -> float:
    return (
        alpha * candidate["content_similarity"]
        + (1 - alpha) * candidate["tag_similarity"]
    )


def _collect_tag_keys(
    matches: list[PineconeMatch], tag_registry: TagRegistry
) -> list[str]:
    unique_keys: set[str] = set()
    for match in matches:
        tags_by_tier = build_tags_by_tier(match.metadata, tag_registry)
        for tags in tags_by_tier.values():
            unique_keys.update(tags)
    return sorted(unique_keys)


class Retriever:
    def __init__(
        self,
        embedder: OpenAIEmbeddingClient,
        chunk_index: PineconeClient,
        tags_index: PineconeClient,
        tag_registry: TagRegistry | None = None,
    ) -> None:
        self._embedder = embedder
        self._chunk_index = chunk_index
        self._tags_index = tags_index
        self._tag_registry = tag_registry or TagRegistry()

    async def retrieve(
        self,
        query: str,
        *,
        candidate_pool: int = 100,
        top_k: int = 10,
    ) -> list[RetrievalResult]:
        query_vector, _ = await self._embedder.embed_texts([query])
        query_vector = query_vector[0]
        matches = self._chunk_index.query(query_vector, top_k=candidate_pool)

        if not matches:
            return []

        tag_keys = _collect_tag_keys(matches, self._tag_registry)
        tag_vocab_embeddings = self._tags_index.fetch(
            tag_keys,
            batch_size=TAG_FETCH_BATCH_SIZE,
        )

        candidates: list[dict[str, Any]] = []
        for match in matches:
            candidate = {
                "id": match.id,
                "metadata": match.metadata,
                "content_similarity": match.score,
                "tags_by_tier": build_tags_by_tier(match.metadata, self._tag_registry),
            }
            candidate["tag_similarity"] = tag_relevance_score(
                candidate,
                query_vector,
                tag_vocab_embeddings,
            )
            candidate["combined_score"] = combined_score(candidate)
            candidates.append(candidate)

        ranked = sorted(candidates, key=lambda c: c["combined_score"], reverse=True)[
            :top_k
        ]

        return [
            RetrievalResult(
                id=candidate["id"],
                chunk=str(candidate["metadata"].get("chunk", "")),
                page_url=str(candidate["metadata"].get("page_url", "")),
                content_similarity=candidate["content_similarity"],
                tag_similarity=candidate["tag_similarity"],
                combined_score=candidate["combined_score"],
                metadata=candidate["metadata"],
            )
            for candidate in ranked
        ]


async def populate_tag_index(
    embedder: OpenAIEmbeddingClient,
    tags_pinecone: PineconeClient,
    tag_registry: TagRegistry | None = None,
) -> int:
    registry = tag_registry or TagRegistry()
    tag_defs = registry.all_tags()

    entries: list[tuple[str, str, str, str]] = []
    for tag_def in tag_defs:
        tier = priority_to_tier(tag_def.priority)
        if tag_def.name == "licensed_ip_flag":
            tag_values = ("false",) + LICENSED_IP_VALUES
        else:
            tag_values = tag_def.values

        for tag_value in tag_values:
            if tag_value in SENTINEL_TAG_VALUES:
                continue
            entries.append(
                (
                    tag_vector_id(tag_def.name, tag_value),
                    tag_def.name,
                    tier,
                    tag_value,
                )
            )

    if not entries:
        return 0

    vectors: list[dict[str, Any]] = []
    for start in range(0, len(entries), TAG_EMBED_BATCH_SIZE):
        batch = entries[start : start + TAG_EMBED_BATCH_SIZE]
        texts = [
            format_tag_index_embed_phrase(tag_name, tag_value)
            for _, tag_name, _, tag_value in batch
        ]
        embeddings, _ = await embedder.embed_texts(texts)

        for (vector_id, tag_name, tier, tag_value), embedding, text in zip(
            batch, embeddings, texts
        ):
            vectors.append(
                {
                    "id": vector_id,
                    "values": embedding,
                    "metadata": {
                        "tag_name": tag_name,
                        "priority": tier,
                        "tag_value": tag_value,
                        "text": text,
                    },
                }
            )

    upserted = tags_pinecone.upsert(vectors, batch_size=TAG_EMBED_BATCH_SIZE)
    log_pretty(
        "Tag index population completed",
        {
            "vector_count": upserted,
            "tag_count": len(tag_defs),
        },
    )
    logger.info("Populated tag index with %d vectors", upserted)
    return upserted

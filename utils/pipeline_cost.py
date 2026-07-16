from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

HASDATA_CREDITS_PER_SCRAPE = 10

# Multipliers relative to base input price (Anthropic prompt caching, 5m TTL).
CACHE_WRITE_5M_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1

# USD per 1M tokens: (input, output). Embedding models use input only.
_MODEL_RATES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "text-embedding-3-small": (0.02, 0.0),
    "en_core_web_md": (0.0, 0.0),
}

COST_OUTPUT_DIR = Path("output")


def cost_report_path_for_run(started_at: datetime) -> Path:
    stamp = started_at.strftime("%Y%m%d_%H%M%S")
    return COST_OUTPUT_DIR / f"cost_endured_{stamp}.txt"


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @classmethod
    def from_anthropic(cls, usage: object | None) -> TokenUsage:
        if usage is None:
            return cls()
        return cls(
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            cache_creation_input_tokens=int(
                getattr(usage, "cache_creation_input_tokens", 0) or 0
            ),
            cache_read_input_tokens=int(
                getattr(usage, "cache_read_input_tokens", 0) or 0
            ),
        )

    @classmethod
    def from_openai_embedding(cls, usage: object | None) -> TokenUsage:
        if usage is None:
            return cls()
        total = getattr(usage, "total_tokens", None)
        if total is None:
            total = getattr(usage, "prompt_tokens", 0) or 0
        return cls(input_tokens=int(total), output_tokens=0)


@dataclass
class ArticleCost:
    page_url: str
    claude_usd: float = 0.0
    hasdata_credits: int = 0
    embedding_usd: float = 0.0


def usd_for_model(model: str, usage: TokenUsage) -> float:
    input_rate, output_rate = _rates_for(model)
    return (
        usage.input_tokens * input_rate
        + usage.cache_creation_input_tokens * input_rate * CACHE_WRITE_5M_MULTIPLIER
        + usage.cache_read_input_tokens * input_rate * CACHE_READ_MULTIPLIER
        + usage.output_tokens * output_rate
    ) / 1_000_000


def _rates_for(model: str) -> tuple[float, float]:
    for key, rates in _MODEL_RATES_PER_MTOK.items():
        if model == key or model.startswith(key):
            return rates
    raise ValueError(f"No pricing rates configured for model={model!r}")


def format_cost_report(rows: list[ArticleCost]) -> str:
    header = "article_url | claude_cost_usd | hasdata_credits | embedding_cost_usd"
    lines = [header]
    for row in rows:
        lines.append(
            f"{row.page_url} | {_fmt_usd(row.claude_usd)} | "
            f"{row.hasdata_credits} | {_fmt_usd(row.embedding_usd)}"
        )

    total = ArticleCost(
        page_url="TOTAL",
        claude_usd=sum(r.claude_usd for r in rows),
        hasdata_credits=sum(r.hasdata_credits for r in rows),
        embedding_usd=sum(r.embedding_usd for r in rows),
    )
    lines.append(
        f"{total.page_url} | {_fmt_usd(total.claude_usd)} | "
        f"{total.hasdata_credits} | {_fmt_usd(total.embedding_usd)}"
    )
    return "\n".join(lines) + "\n"


def write_cost_report(rows: list[ArticleCost], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_cost_report(rows), encoding="utf-8")
    return path


def _fmt_usd(value: float) -> str:
    return f"{value:.6f}"


def article_cost_from_steps(page_url: str, steps: dict) -> ArticleCost:
    """Sum cost fields attached to ok step outcomes."""
    cost = ArticleCost(page_url=page_url)
    for step in steps.values():
        if step.get("status") != "ok":
            continue
        payload = step.get("cost") or {}
        cost.claude_usd += float(payload.get("claude_usd", 0.0))
        cost.hasdata_credits += int(payload.get("hasdata_credits", 0))
        cost.embedding_usd += float(payload.get("embedding_usd", 0.0))
    return cost

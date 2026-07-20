"""Split single_articles.json into domain-diverse batches.

Dedupes with clean_page_url (strip query params + trailing slash/backslash),
interleaves URLs by domain, then deals them round-robin across batches so
every batch gets a rich domain mix. Each cleaned URL appears in exactly one
batch.

Sizes: full batches of BATCH_SIZE, last batch = remainder.

Output: input_urls/article_batches/batch_01.json …
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.url import clean_page_url

DEFAULT_INPUT = ROOT / "input_urls" / "single_articles.json"
DEFAULT_OUTPUT_DIR = ROOT / "input_urls" / "article_batches"
NUM_BATCHES = 7
BATCH_SIZE = 1000
DEFAULT_SEED = 42


def domain_of(url: str) -> str:
    return urlparse(url).netloc.lower()


def interleave_by_domain(
    items: list[dict[str, Any]], *, seed: int
) -> list[dict[str, Any]]:
    """Round-robin across domains (largest first)."""
    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_domain[domain_of(item["url"])].append(item)

    rng = random.Random(seed)
    domains = sorted(by_domain.keys(), key=lambda d: (-len(by_domain[d]), d))
    for domain in domains:
        rng.shuffle(by_domain[domain])

    queues = [by_domain[d] for d in domains]
    interleaved: list[dict[str, Any]] = []
    while any(queues):
        for queue in queues:
            if queue:
                interleaved.append(queue.pop())
    return interleaved


def deal_into_batches(
    items: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Deal interleaved items across batches, then rebalance to exact sizes.

    Dealing (i % N) keeps domain mix even in every batch. Rebalance moves the
    few extras into the last batch so sizes are 1000x6 + remainder.
    """
    piles: list[list[dict[str, Any]]] = [[] for _ in range(NUM_BATCHES)]
    for i, item in enumerate(items):
        piles[i % NUM_BATCHES].append(item)

    targets = [BATCH_SIZE] * (NUM_BATCHES - 1)
    targets.append(len(items) - BATCH_SIZE * (NUM_BATCHES - 1))

    # Move overflow from early batches into undersized ones (prefer last).
    for i in range(NUM_BATCHES - 1):
        while len(piles[i]) > targets[i]:
            item = piles[i].pop()
            # Prefer the last batch; else any still under target.
            dest = NUM_BATCHES - 1
            if len(piles[dest]) >= targets[dest]:
                dest = next(
                    b
                    for b in range(NUM_BATCHES)
                    if len(piles[b]) < targets[b]
                )
            piles[dest].append(item)

    return piles


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Split single_articles.json into domain-diverse batches."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Input JSON (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Shuffle seed for reproducibility (default: {DEFAULT_SEED})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    items: list[dict[str, Any]] = json.loads(args.input.read_text(encoding="utf-8"))
    if not items:
        raise SystemExit(f"No items in {args.input}")

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        url = item.get("url") or item.get("page_url") or ""
        if not isinstance(url, str) or not url.strip():
            continue
        cleaned = clean_page_url(url.strip())
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        cleaned_item = {k: v for k, v in item.items() if k != "page_url"}
        cleaned_item["url"] = cleaned
        unique.append(cleaned_item)

    interleaved = interleave_by_domain(unique, seed=args.seed)
    batches = deal_into_batches(interleaved)

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    all_urls: list[str] = []
    for i, batch in enumerate(batches, start=1):
        path = output_dir / f"batch_{i:02d}.json"
        path.write_text(json.dumps(batch, indent=2) + "\n", encoding="utf-8")
        domains = {domain_of(x["url"]) for x in batch}
        all_urls.extend(x["url"] for x in batch)
        print(
            f"batch_{i:02d}.json: {len(batch)} urls, "
            f"{len(domains)} unique domains -> {path}"
        )

    if len(all_urls) != len(set(all_urls)):
        raise SystemExit("ERROR: duplicate URLs across batches")
    if len(all_urls) != len(unique):
        raise SystemExit(
            f"ERROR: wrote {len(all_urls)} urls but expected {len(unique)}"
        )

    print(f"Total: {len(all_urls)} unique URLs across {len(batches)} batches")


if __name__ == "__main__":
    main()

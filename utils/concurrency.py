from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


async def map_concurrent(
    items: Sequence[T],
    concurrency: int,
    fn: Callable[[T], Awaitable[R]],
) -> list[R]:
    """Run ``fn`` over ``items`` with at most ``concurrency`` in flight.

    Results stay in input order. ``concurrency=1`` is strictly sequential.
    """
    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")
    if not items:
        return []
    if concurrency == 1:
        return [await fn(item) for item in items]

    sem = asyncio.Semaphore(concurrency)

    async def run(item: T) -> R:
        async with sem:
            return await fn(item)

    return list(await asyncio.gather(*(run(item) for item in items)))

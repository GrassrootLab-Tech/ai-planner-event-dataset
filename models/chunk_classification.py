from typing import Literal

from pydantic import BaseModel


class ChunkClassificationItem(BaseModel):
    chunk_index: int
    classification: Literal["usable", "not_usable"]


class ArticleClassificationResult(BaseModel):
    chunks: list[ChunkClassificationItem]

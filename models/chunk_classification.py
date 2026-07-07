from typing import Literal

from pydantic import BaseModel, Field


class ChunkClassificationItem(BaseModel):
    chunk_index: int
    classification: Literal["usable", "not_usable"]
    confidence: float = Field(ge=0.0, le=1.0)


class ArticleClassificationResult(BaseModel):
    chunks: list[ChunkClassificationItem]

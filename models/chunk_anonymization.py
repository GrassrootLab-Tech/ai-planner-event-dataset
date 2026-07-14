from pydantic import BaseModel


class ChunkAnonymizationItem(BaseModel):
    chunk_index: int
    anonymized_text: str


class ArticleAnonymizationResult(BaseModel):
    chunks: list[ChunkAnonymizationItem]

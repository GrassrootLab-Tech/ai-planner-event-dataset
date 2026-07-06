from typing import Literal

from pydantic import BaseModel, Field


class ChunkClassificationResult(BaseModel):
    classification: Literal["usable", "not_usable"]
    confidence: float = Field(ge=0.0, le=1.0)

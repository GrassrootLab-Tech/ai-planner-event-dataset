from datetime import datetime
from typing import Any

from pydantic import BaseModel


class IsUsable(BaseModel):
    value: bool


class EventScrapedChunk(BaseModel):
    page_url: str
    chunk: str
    parent_section_heading: str | None = None
    scraped_at: datetime
    is_usable: IsUsable | None = None
    metadata_tags: dict[str, Any] | None = None

    def to_mongo(self) -> dict:
        return self.model_dump()

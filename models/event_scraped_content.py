from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["scraped", "chunked", "usability_classification", "ai_tagged", "embedded"]


class EventScrapedContent(BaseModel):
    page_url: str
    website: str
    raw_html: str
    markdown: str
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Status = "scraped"

    def to_mongo(self) -> dict:
        return self.model_dump()

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

Status = Literal["scraped", "chunked", "usability_classification", "ai_tagged", "embedded"]


class EventScrapedContent(BaseModel):
    page_url: str
    website: str
    raw_html: str | None = None
    markdown: str | None = None
    reddit_data: dict[str, Any] | None = None
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Status = "scraped"

    def to_mongo(self) -> dict:
        return self.model_dump(exclude_none=True)

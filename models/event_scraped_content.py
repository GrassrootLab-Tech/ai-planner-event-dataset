from datetime import datetime, timezone

from pydantic import BaseModel, Field


class EventScrapedContent(BaseModel):
    page_url: str
    website: str
    raw_html: str
    markdown: str
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_mongo(self) -> dict:
        return self.model_dump()

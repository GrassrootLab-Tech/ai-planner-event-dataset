from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

Status = Literal[
    "scraped",
    "chunked",
    "usability_classification",
    "claude_batch_queued",
    "ai_tagged",
    "anonymized",
    "embedded",
    "failed",
]


class EventScrapedContent(BaseModel):
    page_url: str
    website: str
    page_title: str | None = None
    raw_html: str | None = None
    markdown: str | None = None
    reddit_data: dict[str, Any] | None = None
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Status = "scraped"
    claude_task_id: str | None = None

    def to_mongo(self) -> dict:
        return self.model_dump(exclude_none=True)

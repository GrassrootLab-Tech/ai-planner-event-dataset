from datetime import datetime

from pydantic import BaseModel


class EventScrapedChunk(BaseModel):
    page_url: str
    chunk: str
    parent_section_heading: str | None = None
    scraped_at: datetime

    def to_mongo(self) -> dict:
        return self.model_dump()

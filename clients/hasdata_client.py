from dataclasses import dataclass

import httpx

from utils.logger import log_pretty, logger


class ScrapeError(Exception):
    pass


@dataclass
class ScrapeResult:
    raw_html: str
    markdown: str


class HasDataClient:
    BASE_URL = "https://api.hasdata.com/scrape/web"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def scrape(self, page_url: str) -> ScrapeResult:
        payload = {
            "url": page_url,
            "outputFormat": ["html", "markdown"],
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
        }

        log_pretty("Calling HasData API", {
            "url": self.BASE_URL,
            "payload": payload,
        })

        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(self.BASE_URL, json=payload, headers=headers)

        logger.info("HasData responded with status=%s", response.status_code)

        if response.status_code != 200:
            raise ScrapeError(
                f"HasData request failed with status {response.status_code}: {response.text}"
            )

        data = response.json()
        metadata = data.get("requestMetadata", {})
        log_pretty("HasData response metadata", metadata)

        if metadata.get("status") != "ok":
            raise ScrapeError(f"HasData scrape failed: {metadata}")

        raw_html = data.get("content")
        markdown = data.get("markdown")
        if not raw_html or not markdown:
            raise ScrapeError("HasData response missing content or markdown")

        log_pretty("HasData scrape result", {
            "raw_html_length": len(raw_html),
            "markdown_length": len(markdown),
            "markdown_preview": markdown,
        })

        return ScrapeResult(raw_html=raw_html, markdown=markdown)

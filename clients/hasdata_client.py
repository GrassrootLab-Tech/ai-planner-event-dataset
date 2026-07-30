from dataclasses import dataclass

import httpx

from utils.logger import log_pretty, logger


class ScrapeError(Exception):
    pass


@dataclass
class ScrapeResult:
    raw_html: str
    markdown: str


@dataclass
class DirectoryScrapeResult:
    markdown: str
    links: list[str]


class HasDataClient:
    BASE_URL = "https://api.hasdata.com/scrape/web"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def scrape(self, page_url: str) -> ScrapeResult:
        payload = {
            "url": page_url,
            "outputFormat": ["html", "markdown"],
            "proxyType": "datacenter",
            "proxyCountry": "US",
            "jsRendering": True,
            "blockResources": True,
            "blockAds": True,
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

    async def scrape_directory(self, page_url: str) -> DirectoryScrapeResult:
        """Markdown + extracted links only (no HTML required)."""
        payload = {
            "url": page_url,
            "outputFormat": ["json", "markdown"],
            "extractLinks": True,
            "proxyType": "datacenter",
            "proxyCountry": "US",
            "jsRendering": True,
            "blockResources": True,
            "blockAds": True,
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
        }

        log_pretty("Calling HasData directory scrape", {
            "url": self.BASE_URL,
            "payload": payload,
        })

        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(self.BASE_URL, json=payload, headers=headers)

        logger.info("HasData directory scrape status=%s", response.status_code)

        if response.status_code != 200:
            raise ScrapeError(
                f"HasData request failed with status {response.status_code}: {response.text}"
            )

        data = response.json()
        metadata = data.get("requestMetadata", {})
        if metadata.get("status") != "ok":
            raise ScrapeError(f"HasData scrape failed: {metadata}")

        markdown = data.get("markdown")
        if not markdown:
            raise ScrapeError("HasData directory response missing markdown")

        links = self._normalize_links(
            data.get("links") or data.get("extractedLinks") or []
        )
        log_pretty(
            "HasData directory scrape result",
            {"markdown_length": len(markdown), "link_count": len(links)},
        )
        return DirectoryScrapeResult(markdown=markdown, links=links)

    @staticmethod
    def _normalize_links(raw: object) -> list[str]:
        links: list[str] = []
        seen: set[str] = set()
        if not isinstance(raw, list):
            return links
        for item in raw:
            href: str | None = None
            if isinstance(item, str):
                href = item.strip()
            elif isinstance(item, dict):
                for key in ("url", "href", "link"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        href = value.strip()
                        break
            if not href or href in seen:
                continue
            seen.add(href)
            links.append(href)
        return links

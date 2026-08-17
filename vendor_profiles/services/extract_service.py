from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlparse

from utils.logger import logger
from utils.markdown_cleaner import clean_markdown
from utils.pipeline_cost import TokenUsage
from vendor_profiles.clients.anthropic_vendor_extract_client import (
    AnthropicVendorExtractClient,
)
from vendor_profiles.db.extracted_profiles_repo import (
    VendorsExtractedProfilesRepository,
)
from vendor_profiles.db.profiles_repo import (
    EXTRACT_ELIGIBLE_STATUS,
    EXTRACTED_STATUS,
    EXTRACTION_SKIPPED_STATUS,
    VendorsScrapedProfilesRepository,
)
from vendor_profiles.parsers import get_parser_for_url
from vendor_profiles.parsers.base import VendorProfileParser

# Scrape error payloads sometimes land in markdown as-is; do not extract these.
_SCRAPE_ERROR_MARKERS = (
    "timeout: pool waiting exceeded",
    "403 ERROR",
)


def _markdown_has_scrape_error(markdown: str) -> bool:
    return any(marker in markdown for marker in _SCRAPE_ERROR_MARKERS)


def source_from_page_url(page_url: str) -> str:
    host = urlparse(page_url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or "unknown"


@dataclass
class ExtractOutcome:
    page_url: str
    outcome: str  # extracted | skipped | error
    detail: str = ""
    haiku_usage: TokenUsage = field(default_factory=TokenUsage)
    profile_payload: dict | None = None
    extraction_method: str | None = None  # rules | haiku

    @property
    def ok(self) -> bool:
        return self.outcome != "error"


class VendorExtractService:
    def __init__(
        self,
        *,
        profiles_repo: VendorsScrapedProfilesRepository,
        extracted_repo: VendorsExtractedProfilesRepository,
        extract_client: AnthropicVendorExtractClient | None = None,
        get_parser: Callable[
            [str], VendorProfileParser | None
        ] = get_parser_for_url,
    ) -> None:
        self._profiles = profiles_repo
        self._extracted = extracted_repo
        self._client = extract_client
        self._get_parser = get_parser

    async def extract_url(self, page_url: str) -> ExtractOutcome:
        # Fragment URLs (#deals, #reviews) are page sections, not vendor profiles.
        if "#" in page_url:
            reason = "page_url has # fragment; not a vendor profile URL"
            marked = await self._profiles.mark_extraction_skipped(
                page_url, reason
            )
            if not marked:
                logger.warning(
                    "Fragment URL skip but status was not %s for %s "
                    "(wanted %s)",
                    EXTRACT_ELIGIBLE_STATUS,
                    page_url,
                    EXTRACTION_SKIPPED_STATUS,
                )
            return ExtractOutcome(
                page_url=page_url,
                outcome="skipped",
                detail=f"{reason}; marked {EXTRACTION_SKIPPED_STATUS}",
            )

        doc = await self._profiles.find_scraped_by_page_url(page_url)
        if doc is None:
            return ExtractOutcome(
                page_url=page_url,
                outcome="skipped",
                detail="not found in vendors_scraped_profiles",
            )

        status = doc.get("status")
        if status == EXTRACTED_STATUS:
            return ExtractOutcome(
                page_url=page_url,
                outcome="skipped",
                detail="already extracted",
            )
        if status != EXTRACT_ELIGIBLE_STATUS:
            return ExtractOutcome(
                page_url=page_url,
                outcome="skipped",
                detail=f"status={status!r} (need {EXTRACT_ELIGIBLE_STATUS})",
            )

        markdown = doc.get("markdown")
        if not isinstance(markdown, str) or not markdown.strip():
            return ExtractOutcome(
                page_url=page_url,
                outcome="skipped",
                detail="empty or missing markdown",
            )

        if _markdown_has_scrape_error(markdown):
            await self._profiles.mark_failed(
                page_url,
                "markdown contains scrape error (timeout pool / 403 ERROR)",
            )
            return ExtractOutcome(
                page_url=page_url,
                outcome="skipped",
                detail="scrape error in markdown (timeout/403); marked failed",
            )

        html = doc.get("html") if isinstance(doc.get("html"), str) else None

        parser = self._get_parser(page_url)
        try:
            if parser is not None:
                logger.info(
                    "Rules extract page_url=%s parser=%s raw_chars=%d html_chars=%d",
                    page_url,
                    parser.source_host,
                    len(markdown),
                    len(html) if html else 0,
                )
                profile = parser.parse(page_url, markdown, html=html)
                usage = TokenUsage()
                method = "rules"
            else:
                if self._client is None:
                    return ExtractOutcome(
                        page_url=page_url,
                        outcome="skipped",
                        detail="no rule parser and no Haiku extract client",
                    )
                cleaned = clean_markdown(markdown, keep_links=True)
                if not cleaned.strip():
                    return ExtractOutcome(
                        page_url=page_url,
                        outcome="skipped",
                        detail="markdown empty after cleaning",
                    )
                logger.info(
                    "Cleaned markdown for extract page_url=%s "
                    "raw_chars=%d cleaned_chars=%d",
                    page_url,
                    len(markdown),
                    len(cleaned),
                )
                profile, usage = await self._client.extract_profile(
                    page_url=page_url,
                    markdown=cleaned,
                )
                method = "haiku"

            profile_fields = profile.model_dump(mode="json", exclude_none=True)
            slug = profile_fields.get("slug")
            if not isinstance(slug, str) or not slug.strip():
                return ExtractOutcome(
                    page_url=page_url,
                    outcome="skipped",
                    detail="missing slug; not writing extracted profile",
                    haiku_usage=usage,
                    extraction_method=method,
                )
            source = source_from_page_url(page_url)
            written = await self._extracted.upsert_extracted(
                page_url=page_url,
                source=source,
                profile_fields=profile_fields,
            )
            if not written:
                # Duplicate (page_url or source+slug); still mark so we don't retry.
                marked = await self._profiles.mark_extracted(page_url)
                if not marked:
                    logger.warning(
                        "Duplicate extract skipped but status was not %s for %s",
                        EXTRACT_ELIGIBLE_STATUS,
                        page_url,
                    )
                return ExtractOutcome(
                    page_url=page_url,
                    outcome="skipped",
                    detail="duplicate page_url or source+slug",
                    haiku_usage=usage,
                    profile_payload=profile_fields,
                    extraction_method=method,
                )
            marked = await self._profiles.mark_extracted(page_url)
            if not marked:
                logger.warning(
                    "Extracted profile saved but status was not %s for %s",
                    EXTRACT_ELIGIBLE_STATUS,
                    page_url,
                )
            return ExtractOutcome(
                page_url=page_url,
                outcome="extracted",
                haiku_usage=usage,
                profile_payload=profile_fields,
                extraction_method=method,
            )
        except Exception as exc:
            logger.exception("extract failed for %s", page_url)
            await self._profiles.mark_extraction_failed(page_url, str(exc))
            return ExtractOutcome(
                page_url=page_url,
                outcome="error",
                detail=str(exc),
            )

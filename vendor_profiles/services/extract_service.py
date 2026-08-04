from __future__ import annotations

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
    VendorsScrapedProfilesRepository,
)


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

    @property
    def ok(self) -> bool:
        return self.outcome != "error"


class VendorExtractService:
    def __init__(
        self,
        *,
        profiles_repo: VendorsScrapedProfilesRepository,
        extracted_repo: VendorsExtractedProfilesRepository,
        extract_client: AnthropicVendorExtractClient,
    ) -> None:
        self._profiles = profiles_repo
        self._extracted = extracted_repo
        self._client = extract_client

    async def extract_url(self, page_url: str) -> ExtractOutcome:
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

        cleaned = clean_markdown(markdown, keep_links=True)
        if not cleaned.strip():
            return ExtractOutcome(
                page_url=page_url,
                outcome="skipped",
                detail="markdown empty after cleaning",
            )
        logger.info(
            "Cleaned markdown for extract page_url=%s raw_chars=%d cleaned_chars=%d",
            page_url,
            len(markdown),
            len(cleaned),
        )

        try:
            profile, usage = await self._client.extract_profile(
                page_url=page_url,
                markdown=cleaned,
            )
            profile_fields = profile.model_dump(mode="json", exclude_none=True)
            source = source_from_page_url(page_url)
            await self._extracted.upsert_extracted(
                page_url=page_url,
                source=source,
                profile_fields=profile_fields,
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
            )
        except Exception as exc:
            logger.exception("extract failed for %s", page_url)
            return ExtractOutcome(
                page_url=page_url,
                outcome="error",
                detail=str(exc),
            )

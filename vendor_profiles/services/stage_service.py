from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from clients.hasdata_client import HasDataClient, ScrapeError
from utils.pipeline_cost import TokenUsage
from utils.url import clean_page_url
from vendor_profiles.clients.anthropic_vendor_link_client import AnthropicVendorLinkClient
from vendor_profiles.db.directory_urls_repo import VendorsScrapedDirectoryUrlsRepository
from vendor_profiles.db.profiles_repo import VendorsScrapedProfilesRepository
from vendor_profiles.partyslate_listing_api import (
    convert_partyslate_url,
    extract_json_payload,
    is_partyslate_host,
    listing_profile_urls,
    profile_kind,
)
from vendor_profiles.services.scrape_service import (
    EMPTY_MARKDOWN_ERROR,
    is_empty_markdown,
)
from vendor_profiles.source_rules import (
    TYPE_SINGLE_VENDOR,
    TYPE_UNKNOWN,
    classify_url,
    extract_vendor_profile_urls,
    get_rules_for_url,
    normalize_source_host,
)
from vendor_profiles.sources import DISABLED_STAGE_SCRAPE_HOSTS

VENDOR_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
VENDOR_STAGE_REPORT_PATH = VENDOR_OUTPUT_DIR / "vendor_stage_report.txt"


@dataclass
class StageResult:
    page_url: str
    outcome: str
    detail: str = ""
    profiles_inserted: int = 0
    haiku_usage: TokenUsage = field(default_factory=TokenUsage)

    @property
    def ok(self) -> bool:
        return self.outcome != "error"


class VendorStageService:
    def __init__(
        self,
        *,
        profiles_repo: VendorsScrapedProfilesRepository,
        directory_repo: VendorsScrapedDirectoryUrlsRepository,
        hasdata: HasDataClient,
        link_client: AnthropicVendorLinkClient | None = None,
        report_path: Path = VENDOR_STAGE_REPORT_PATH,
    ) -> None:
        self._profiles = profiles_repo
        self._directories = directory_repo
        self._hasdata = hasdata
        self._link_client = link_client
        self._report_path = report_path

    async def stage_url(
        self,
        page_url: str,
        *,
        page_title: str | None = None,
    ) -> StageResult:
        cleaned = clean_page_url(page_url.strip())
        if not cleaned:
            return StageResult(page_url=page_url, outcome="error", detail="empty url")

        host = normalize_source_host(cleaned)
        if host in DISABLED_STAGE_SCRAPE_HOSTS:
            return StageResult(
                page_url=cleaned,
                outcome="skipped_disabled",
                detail=f"source {host} temporarily disabled for stage/scrape",
            )

        if await self._profiles.exists_as_page_or_parent(cleaned):
            return StageResult(
                page_url=cleaned,
                outcome="skipped_existing",
                detail="page_url or parent_page_url already present",
            )

        if await self._directories.exists_by_page_url(cleaned):
            return StageResult(
                page_url=cleaned,
                outcome="skipped_existing_directory",
                detail="page_url already present in directory collection",
            )

        rules = get_rules_for_url(cleaned)
        if rules is None:
            self._append_report(f"no_rules\t{cleaned}")
            return StageResult(
                page_url=cleaned,
                outcome="skipped_no_rules",
                detail="no regex rules for source host",
            )

        url_type = classify_url(rules, cleaned)
        if url_type in (TYPE_UNKNOWN, "unmatched", "unknown_source", "unknown"):
            self._append_report(f"unknown\t{cleaned}")
            return StageResult(
                page_url=cleaned,
                outcome="skipped_unknown",
                detail="url matched neither directory nor profile regex",
            )

        if url_type in (TYPE_SINGLE_VENDOR, "profile", "single_vendor"):
            inserted = await self._profiles.insert_pending(
                cleaned, parent_page_url=None
            )
            if inserted:
                await self._profiles.set_status(cleaned, "staged")
            return StageResult(
                page_url=cleaned,
                outcome="single_vendor",
                profiles_inserted=1 if inserted else 0,
            )

        if is_partyslate_host(cleaned):
            return await self._stage_partyslate_directory(cleaned)

        scrape = await self._hasdata.scrape_directory(cleaned)
        if is_empty_markdown(scrape.markdown):
            await self._directories.upsert_scrape(
                page_url=cleaned,
                markdown=scrape.markdown,
                all_links=scrape.links,
                status="failed",
                error=EMPTY_MARKDOWN_ERROR,
            )
            return StageResult(
                page_url=cleaned,
                outcome="error",
                detail=EMPTY_MARKDOWN_ERROR,
            )

        await self._directories.upsert_scrape(
            page_url=cleaned,
            markdown=scrape.markdown,
            all_links=scrape.links,
            status="ok",
        )

        cleaned_profiles = extract_vendor_profile_urls(
            cleaned,
            all_links=scrape.links,
            markdown=scrape.markdown,
        )
        usage = TokenUsage()

        await self._directories.set_vendor_profile_urls(cleaned, cleaned_profiles)

        inserted_urls: list[str] = []
        for profile in cleaned_profiles:
            ok = await self._profiles.insert_pending(
                profile, parent_page_url=cleaned
            )
            if ok:
                inserted_urls.append(profile)

        if inserted_urls:
            await self._profiles.set_status_many(inserted_urls, "staged")

        return StageResult(
            page_url=cleaned,
            outcome="vendors_directory",
            detail=f"links={len(scrape.links)} profiles={len(cleaned_profiles)}",
            profiles_inserted=len(inserted_urls),
            haiku_usage=usage,
        )

    async def _stage_partyslate_directory(self, cleaned: str) -> StageResult:
        try:
            api_url = convert_partyslate_url(cleaned)
        except ValueError as exc:
            await self._directories.upsert_scrape(
                page_url=cleaned,
                markdown="",
                all_links=[],
                html="",
                status="failed",
                error=str(exc),
            )
            return StageResult(
                page_url=cleaned,
                outcome="error",
                detail=str(exc),
            )

        try:
            body = await self._hasdata.scrape_api_json(api_url)
        except ScrapeError as exc:
            await self._directories.upsert_scrape(
                page_url=cleaned,
                markdown="",
                all_links=[],
                html="",
                status="failed",
                error=str(exc),
            )
            return StageResult(
                page_url=cleaned,
                outcome="error",
                detail=str(exc),
            )

        payload = extract_json_payload(body)
        html = ""
        content = body.get("content")
        if isinstance(content, str) and content:
            html = content
        elif isinstance(body.get("html"), str):
            html = body["html"]

        if payload is None:
            await self._directories.upsert_scrape(
                page_url=cleaned,
                markdown="",
                all_links=[],
                html=html,
                status="failed",
                error="failed to parse PartySlate listing JSON",
            )
            return StageResult(
                page_url=cleaned,
                outcome="error",
                detail="failed to parse PartySlate listing JSON",
            )

        kind = profile_kind(api_url)
        cleaned_profiles = listing_profile_urls(payload, kind)

        await self._directories.upsert_scrape(
            page_url=cleaned,
            markdown="",
            all_links=[],
            html=html,
            status="ok",
        )
        await self._directories.set_vendor_profile_urls(cleaned, cleaned_profiles)

        inserted_urls: list[str] = []
        for profile in cleaned_profiles:
            ok = await self._profiles.insert_pending(
                profile, parent_page_url=cleaned
            )
            if ok:
                inserted_urls.append(profile)

        if inserted_urls:
            await self._profiles.set_status_many(inserted_urls, "staged")

        return StageResult(
            page_url=cleaned,
            outcome="vendors_directory",
            detail=(
                f"partyslate_api profiles={len(cleaned_profiles)} "
                f"kind={kind}"
            ),
            profiles_inserted=len(inserted_urls),
        )

    def _append_report(self, line: str) -> None:
        self._report_path.parent.mkdir(parents=True, exist_ok=True)
        with self._report_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

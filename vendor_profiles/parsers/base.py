from __future__ import annotations

from abc import ABC, abstractmethod

from vendor_profiles.models.vendor_profile import VendorProfile


class VendorProfileParser(ABC):
    """Hand-written per-source markdown → VendorProfile parser."""

    source_host: str

    @abstractmethod
    def slug_from_url(self, page_url: str) -> str | None:
        """Extract vendor slug from the page URL path (source-specific rules)."""

    @abstractmethod
    def parse(
        self,
        page_url: str,
        markdown: str,
        *,
        html: str | None = None,
    ) -> VendorProfile:
        """Parse scraped profile markdown into a VendorProfile.

        ``html`` is optional raw page HTML for sources that embed contact
        fields outside markdown (e.g. PartySlate JSON-LD).

        Raises ValueError when business_name cannot be determined.
        """

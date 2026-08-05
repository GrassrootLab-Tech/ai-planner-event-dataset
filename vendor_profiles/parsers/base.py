from __future__ import annotations

from abc import ABC, abstractmethod

from vendor_profiles.models.vendor_profile import VendorProfile


class VendorProfileParser(ABC):
    """Hand-written per-source markdown → VendorProfile parser."""

    source_host: str

    @abstractmethod
    def parse(self, page_url: str, markdown: str) -> VendorProfile:
        """Parse scraped profile markdown into a VendorProfile.

        Raises ValueError when business_name cannot be determined.
        """

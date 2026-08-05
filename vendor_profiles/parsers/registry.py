from __future__ import annotations

from vendor_profiles.parsers.base import VendorProfileParser
from vendor_profiles.parsers.gigsalad import GigSaladProfileParser
from vendor_profiles.parsers.thebash import TheBashProfileParser
from vendor_profiles.source_rules import normalize_source_host

PARSERS: dict[str, VendorProfileParser] = {
    p.source_host: p
    for p in (
        TheBashProfileParser(),
        GigSaladProfileParser(),
    )
}


def get_parser_for_url(page_url: str) -> VendorProfileParser | None:
    """Return the hand-written parser for this URL's host, or None."""
    host = normalize_source_host(page_url)
    if not host:
        return None
    return PARSERS.get(host)

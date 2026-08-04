# Run vendor staging with:
#   python -m vendor_profiles stage
#   python -m vendor_profiles stage --concurrency 3
# page_title is optional — used as context when filtering directory links.

PAGE_URLS: list[dict[str, str | None]] = [
    {
        "page_url": "https://www.thebash.com/search/blues-band-denver-co",
        "page_title": None,
    },
]

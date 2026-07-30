# Run vendor staging with:
#   python -m vendor_profiles stage
#   python -m vendor_profiles stage --concurrency 3
# page_title is optional — used as context when filtering directory links.

PAGE_URLS: list[dict[str, str | None]] = [
    {
        "page_url": "https://www.thebash.com/search/live-band-denver-co",
        "page_title": "Top 20 Live Bands for Hire in Denver, CO",
    },
    {
        "page_url": "https://www.thebash.com/search/singer-denver-co",
        "page_title": "Top 20 Singers for Hire in Denver, CO",
    },
    {
        "page_url": "https://www.thebash.com/variety-band/mark-ham-band",
        "page_title": "Mark Ham Band - Variety Band for Hire in Denver, CO",
    },
    {
        "page_url": "https://www.gigsalad.com/Solo-Musicians/All/CO/Denver",
        "page_title": "Best Solo Musicians for Hire in Denver, CO (with Reviews)",
    },
    {
        "page_url": "https://www.gigsalad.com/Musicians/All/CO/Denver",
        "page_title": "Best Musicians for Hire in Denver, CO (with Reviews)",
    },
    {
        "page_url": "https://www.thebash.com/search/live-band-denver-co",
        "page_title": "Top 20 Live Bands for Hire in Denver, CO",
    },
    {
        "page_url": "https://www.gigsalad.com/Event-Services/Caterer/CO/Denver",
        "page_title": "Top 20 Caterers for Hire in Denver, CO",
    },
    {
        "page_url": "https://www.gigsalad.com/Event-Services/Food-Truck/CO/Littleton",
        "page_title": "Top 20 Food Trucks for Hire in Littleton, CO",
    },
]

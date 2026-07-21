# Run this local list with:
#   python main.py run-all-sample
#   python main.py run-stage-batch scrape --limit 5
# Or supply a JSON batch:
#   python main.py run-all-sample input_urls/article_batches/batch_01.json
#   python main.py run-stage-batch scrape input_urls/article_batches/batch_01.json --limit 10
# Progress: output/batch_report.txt / output/stage_batch_report.txt
# page_title is optional — set to None to omit it from tagging.

PAGE_URLS: list[dict[str, str | None]] = [
    {
        "page_url": "https://www.classpop.com/magazine/birthday-party-ideas-in-atlanta",
        "page_title": "Birthday Party Ideas in Atlanta: 35 Fun Venues & Places to ...",
    },
    {
        "page_url": "https://www.playpartyplan.com/stocking-stuffers-for-men",
        "page_title": "25 Unique Stocking Stuffers for Men Under $10",
    },
    {
        "page_url": "https://www.thebash.com/articles/bachelorette-party-theme-ideas",
        "page_title": "60 Trendy Bachelorette Party Theme Ideas",
    },
    {
        "page_url": "https://www.thehouseofbachelorette.com/blogs/bachelorette-ideas/101-bachelorette-party-ideas",
        "page_title": "101 Bachelorette Party Ideas in 2026",
    },
    {
        "page_url": "https://www.thehouseofbachelorette.com/blogs/bachelorette-ideas/60-out-of-the-box-bachelorette-party-ideas-you-wont-believe",
        "page_title": "60+ Out-of-the-Box Bachelorette Party Ideas You Won't ...",
    },
]

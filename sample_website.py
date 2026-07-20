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
        "page_url": "https://www.partypacks.co.uk/blogs/party-inspiration/throw-1920s-gatsby-themed-party",
        "page_title": "Throw a 1920s Gatsby themed party – Party Packs",
    },
    {
        "page_url": "https://www.bonjourfete.com/blogs/le-blog/how-to-host-a-classic-christmas-party-tablescape-decor-ideas",
        "page_title": "how to host a classic christmas party: tablescape & decor ...",
    },
    {
        "page_url": "https://www.bonjourfete.com/blogs/le-blog/how-to-host-a-video-game-birthday-party",
        "page_title": "How to Host a Video Game Birthday Party",
    },
    {
        "page_url": "https://thepartydarling.com/blogs/the-party-darling-blog/outer-space-party",
        "page_title": "Outer Space Birthday Party Ideas",
    },
    {
        "page_url": "https://www.thehouseofbachelorette.com/blogs/bachelorette-ideas/10-best-bachelorette-party-trends",
        "page_title": "10 Best Bachelorette Party Trends of 2026",
    },
]

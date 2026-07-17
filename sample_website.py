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
        "page_url": "https://www.partypacks.co.uk/blogs/party-inspiration/top-10-wedding-favour-ideas-diy-wedding-favours-plus-ideas-for-low-cost-wedding-favour-gift-boxes-bags",
        "page_title": "Top 10 Wedding Favour Ideas - DIY Wedding Favours Plus Ideas For Low Cost Wedding Favour Gift Boxes Bags - Party Packs",
    },
    {
        "page_url": "https://thehenplanner.co.uk/blogs/blog/liverpool-hen-party-ideas",
        "page_title": "Things To Do in Liverpool For a Hen Party!",
    },
    {
        "page_url": "https://www.thehouseofbachelorette.com/blogs/bachelorette-ideas/bachelorette-party-checklist",
        "page_title": "Bachelorette Party Checklist",
    },
]

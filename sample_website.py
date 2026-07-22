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
        "page_url": "https://thecreativeheartstudio.com/blogs/projects/unicorn-kisses-and-rainbow-wishes",
        "page_title": "Unicorn Kisses and Rainbow Wishes",
    },
    {
        "page_url": "https://www.catchmyparty.com/parties/6th-birthday",
        "page_title": 'Cops & Robbers / Birthday "6th Birthday"',
    },
    {
        "page_url": "https://www.ruffledblog.com/brisbane-high-tea-wedding",
        "page_title": "Brisbane High Tea Wedding",
    },
]

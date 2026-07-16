# Add pages to run in batch via: python main.py run-all-sample
# Progress is written to output/batch_report.txt (updated after each URL).
# page_title is optional — set to None to omit it from tagging.

PAGE_URLS: list[dict[str, str | None]] = [
    # {"url": "https://minteventdesign.com/blog/sweetest-unicorn-birthday-party-free-printables", "page_title": None},
    # {"url": "https://www.brides.com/bachelor-party-ideas-5114632", "page_title": None},
    # {"url": "https://blog.chickabug.com/sock-monkey-party/", "page_title": None},
    # {"url": "https://www.classpop.com/magazine/sweet-16-gift-ideas", "page_title": None},
    # {"url": "https://www.ruffledblog.com/summer-bachelorette-party/", "page_title": None},
    # {"url": "https://www.blog.birdsparty.com/2010/11/christmas-candyland-party.html", "page_title": None},
    # {"url": "https://www.theknot.com/content/30a-bachelorette-party", "page_title": None},
    # {"url": "https://www.theknot.com/content/fort-lauderdale-bachelor-party", "page_title": None},
    # {"url": "https://www.groopeze.com/blog/the-cost-of-a-work-christmas-party", "page_title": None},
    # {"url": "http://homemadeparties.ph/2014/11/10/diy-tiger-party", "page_title": None},
    # {"url": "https://www.mooreandcoevents.com/blog/nontraditional-bachelorbachelorette-party-ideas", "page_title": None},
    # {"url": "http://blog.amyatlas.com/2013/06/24/lets-chill-guest-dessert-feature", "page_title": None},
    # {"url": "https://www.littlemisspartyplanner.com/blog/a-guideline-to-planning-a-bar-or-bat-mitzvah-party", "page_title": None},
    # {"url": "https://jordanseasyentertaining.com/shark-party", "page_title": None},
    # {"url": "https://www.tagvenue.com/blog/party-planning-checklist", "page_title": None},
    # {"url": "https://www.blog.birdsparty.com/2018/07/how-to-throw-epic-lake-party-this-summer.html", "page_title": None},
    # {"url": "https://www.peekaboopartybags.co.nz/blog/peekaboo-birthday-present-ideas", "page_title": None},
    # {"url": "https://www.pressprintparty.com/party-ideas/harry-potter-gift-bags-diy", "page_title": None},
    # {"url": "https://partywithunicorns.com/butterfly-theme-party-ideas", "page_title": None},
    # {"url": "https://www.partyslate.com/best-of/25-unique-party-themes-for-2025-celebrations-and-events", "page_title": None},
    # {"url": "https://www.tagvenue.com/blog/summer-party-ideas/", "page_title": None},
    # {"url": "https://www.littlemisspartyplanner.com/blog/a-guideline-to-planning-a-bar-or-bat-mitzvah-party", "page_title": None},
    # {"url": "https://www.tagvenue.com/blog/summer-party-ideas/", "page_title": None},
    # {"url": "https://www.gigsalad.com/blog/beach-wedding/", "page_title": None},
    {"url": "https://www.catchmyparty.com/parties/lemon-lime-its-party-time", "page_title": None},
    # {"url": "https://www.gigsalad.com/blog/beach-wedding/", "page_title": None},
    # {"url": "https://www.brides.com/bachelor-party-ideas-5114632", "page_title": None},
]

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
    # {"url": "https://www.catchmyparty.com/parties/lemon-lime-its-party-time", "page_title": None},
    # {"url": "https://www.gigsalad.com/blog/beach-wedding/", "page_title": None},
    # {"url": "https://www.brides.com/bachelor-party-ideas-5114632", "page_title": None},
    # {
    #     "url": "https://www.momoparty.com/blogs/party-tips-and-more/the-best-fall-party-themes-for-kids",
    #     "page_title": "The Best Fall Party Themes for Kids",
    # },
    # {
    #     "url": "https://ultimatebridesmaid.com/tag/pride-and-prejudice-bridal-shower",
    #     "page_title": "pride and prejudice bridal shower - Ultimate Bridesmaid",
    # },
    {
        "url": "https://thepartydarling.com/blogs/the-party-darling-blog/4th-of-july-party-ideas-to-throw-a-star-spangled-banger",
        "page_title": "4th of July Party Ideas to Throw A Star-Spangled Banger",
    },
    {
        "url": "https://www.classpop.com/magazine/adult-birthday-party-ideas",
        "page_title": "Adult Birthday Party Ideas | Most Creative in 2026",
    },
    {
        "url": "https://partywithunicorns.com/printable-mothers-day-gift-box",
        "page_title": "Printable Mother's Day Gift Box - Free Download",
    },
    {
        "url": "https://blog.amyatlas.com/2014/04/15/bake-shop-dessert-table",
        "page_title": "Bake Shop Dessert Table | Amy Atlas Events",
    },
    {
        "url": "https://www.pumpitupparty.com/blog/what-to-do-when-kids-have-no-school-but-you-have-work",
        "page_title": "What To Do When Kids Have No School But You Have Work",
    },
    {
        "url": "https://www.thebash.com/articles/host-a-dinner-party",
        "page_title": "How to Host a Dinner Party Like a Pro",
    },
    {
        "url": "https://www.giggleliving.com/a-key-west-party-ideas-for-summer-fun",
        "page_title": "A Key West Party theme is a festive way to celebrate summer!",
    },
    {
        "url": "https://www.festivefetti.com/blog/whimsical-halloween-hair-accessories-for-girls",
        "page_title": "Whimsical Halloween Hair Accessories for Girls",
    },
    {
        "url": "https://www.evite.com/blog/inspiration-ideas/summer-luau-party-guide",
        "page_title": "Summer luau party guide",
    },
    {
        "url": "https://www.thehouseofbachelorette.com/blogs/bachelorette-ideas/the-best-ideas-for-your-virginia-bachelorette-party",
        "page_title": "The Best Ideas for your Virginia Bachelorette Party!",
    },
]

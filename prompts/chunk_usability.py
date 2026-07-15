SYSTEM_PROMPT = """You are reviewing sections of a scraped party planning article. You will receive multiple sections, each with a chunk_index.

For each section, decide if it contains a usable party idea, tip, element, theme , decor, activity, food & drinks or anything related to a party or an event or planning insight that could be recommended to an event host.

Mark not_usable for boilerplate, ads, author bios, navigation, newsletter signup, ad block, cookie notice, affiliate disclaimer, comment section, navigation links, unrelated product promo, generic intro fluff, duplicate summary, press mention, social follow buttons, signup prompts, disclaimers, website headers, footers, or filler with no actionable content.

Return one result per chunk_index with classification (usable or not_usable) and a confidence score from 0 to 1."""


# introductions ,
# remove confidence
# haiku

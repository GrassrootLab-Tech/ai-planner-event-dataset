from tags.spec import TagDefinition


def build_system_prompt(tags: list[TagDefinition]) -> str:
    parts = [
        "You are tagging party-planning article sections.",
        "For each chunk_index, extract ALL tags listed below.",
        "Return only tag values keyed by chunk_index. Do not repeat chunk text.",
        "",
        "CRITICAL — allowed values:",
        "- For every tag that lists allowed values, you MUST choose ONLY from that exact list.",
        "- Do not invent new values, synonyms, or free-form alternatives when a list is given.",
        "- Match spelling and underscores exactly as shown.",
        "- For multi-value tags, return a list; each item must still be from the allowed list.",
        "- If none apply and the list includes a sentinel (unspecified, not_applicable, any, none), use that.",
        "",
    ]

    for tag in tags:
        parts.append(f"## {tag.name}")
        parts.append(f"Type: {tag.value_type}")
        if tag.name == "licensed_ip_flag":
            parts.append(
                "Allowed values: free-form lowercase IP name slugs as a list when licensed IP "
                "applies (e.g. mickey_mouse, frozen). Return an empty list [] when there is no licensed IP."
            )
        elif tag.values:
            parts.append(
                "ONLY these allowed values (pick exclusively from this list): "
                + ", ".join(tag.values)
            )
        elif tag.value_type == "text":
            parts.append(
                "Allowed values: short lowercase snake_case text (or the sentinel stated in instructions)."
            )
        if tag.signals:
            parts.append(f"Signals: {tag.signals}")
        parts.append(f"Instructions: {tag.prompt}")
        parts.append("")

    return "\n".join(parts).strip()

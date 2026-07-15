from tags.spec import TagDefinition


def build_system_prompt(tags: list[TagDefinition]) -> str:
    parts = [
        "CRITICAL — allowed values:",
        "- For every tag that lists allowed values, you MUST choose ONLY from that exact list.",
        "- Do not invent new values, synonyms, or free-form alternatives when a list is given.",
        "- Match spelling and underscores exactly as shown.",
        "- For multi-value tags, return a list; each item must still be from the allowed list.",
        "",
        "CRITICAL — sentinel values:",
        "- Some tag instructions permit a sentinel value (e.g. unspecified, not_applicable, none, or an empty list) ",
        "  to represent 'this tag does not apply to this section' or 'the section does not specify this'.",
        "- Do NOT return these sentinel values in the output. Instead, if your determined value for a tag ",
        "  IS one of these sentinels, omit that tag's field entirely from the output for that chunk_index.",
        "- Only omit a field when your own judgment concludes the sentinel applies to this specific section — ",
        "  never omit a field just because the instructions mention these words as allowed options.",
        "- If a tag clearly applies and has a real, supportable value, you MUST include it — do not omit ",
        "  applicable tags for brevity.",
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

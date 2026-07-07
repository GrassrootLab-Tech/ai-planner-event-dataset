from tags.spec import TagDefinition


def build_group_system_prompt(group_id: str, tags: list[TagDefinition]) -> str:
    parts = [
        "You are tagging party-planning article sections.",
        f"Group: {group_id}",
        "For each chunk_index, extract the tags listed below.",
        "Return only tag values keyed by chunk_index. Do not repeat chunk text.",
        "",
    ]

    for tag in tags:
        parts.append(f"## {tag.name}")
        if tag.values:
            parts.append(f"Allowed values: {', '.join(tag.values)}")
        if tag.signals:
            parts.append(f"Signals: {tag.signals}")
        parts.append(f"Instructions: {tag.prompt}")
        parts.append("")

    return "\n".join(parts).strip()

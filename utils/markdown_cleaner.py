import re

_IMAGE_PATTERN = re.compile(
    r"!\[[^\]]*\]\((?:[^()]|\([^()]*\))*\)"
    r'(?:\s+"[^"]*")?'
    r"|!\[[^\]]*\]\[[^\]]*\]",
)
_LINK_PATTERN = re.compile(
    r"\[([^\]]*)\]\((?:[^()]|\([^()]*\))*\)"
    r'(?:\s+"[^"]*")?'
    r"|\[([^\]]*)\]\[[^\]]*\]",
)
_REF_DEF_PATTERN = re.compile(r"^\[[^\]]*\]:\s+\S+.*$", re.MULTILINE)
_AUTOLINK_PATTERN = re.compile(r"<(?:https?://|mailto:)[^>]+>", re.IGNORECASE)
_EMPTY_LIST_ITEM_PATTERN = re.compile(r"^\s*[-*+]\s*$", re.MULTILINE)
_EXCESS_BLANK_LINES_PATTERN = re.compile(r"\n{3,}")
# Collapse spaces/tabs on a line without touching newlines.
_INTRA_LINE_WHITESPACE_PATTERN = re.compile(r"[^\S\n]{2,}")


def clean_markdown(md: str, *, keep_links: bool = False) -> str:
    """Clean scraped markdown noise.

    Default (keep_links=False): strip images/links to link text only — used for
    article chunking.

    keep_links=True: preserve markdown links, images, autolinks, and reference
    definitions so URLs remain available for vendor extraction.
    """
    text = md
    if not keep_links:
        text = _IMAGE_PATTERN.sub("", text)
        text = _LINK_PATTERN.sub(lambda m: m.group(1) or m.group(2) or "", text)
        text = _REF_DEF_PATTERN.sub("", text)
        text = _AUTOLINK_PATTERN.sub("", text)
    text = _EMPTY_LIST_ITEM_PATTERN.sub("", text)
    text = _INTRA_LINE_WHITESPACE_PATTERN.sub(" ", text)
    text = _EXCESS_BLANK_LINES_PATTERN.sub("\n\n", text)
    return text.strip()

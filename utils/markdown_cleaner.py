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


def clean_markdown(md: str) -> str:
    text = _IMAGE_PATTERN.sub("", md)
    text = _LINK_PATTERN.sub(lambda m: m.group(1) or m.group(2) or "", text)
    text = _REF_DEF_PATTERN.sub("", text)
    text = _AUTOLINK_PATTERN.sub("", text)
    text = _EMPTY_LIST_ITEM_PATTERN.sub("", text)
    text = _EXCESS_BLANK_LINES_PATTERN.sub("\n\n", text)
    return text

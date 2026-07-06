import re
from dataclasses import dataclass

HEADING_PATTERN = re.compile(
    r"^\s*"
    r"(?:>\s*)*"
    r"(?:(?:\d+\.\s*|[-*+]\s+))?"
    r"(#{2,4})"
    r"\s*"
    r"(.+)$",
)


@dataclass
class ChunkResult:
    chunk: str
    parent_section_heading: str | None


def _normalize_chunk_text(text: str) -> str:
    """Collapse whitespace for length checks only."""
    return re.sub(r"\s+", " ", text).strip()


def _format_chunk_text(lines: list[str]) -> str:
    return "\n".join(lines).strip()


def _heading_level(marker: str) -> int:
    return len(marker)


def _parent_heading(heading_stack: list[tuple[int, str]], level: int) -> str | None:
    for stack_level, text in reversed(heading_stack):
        if stack_level < level:
            return text
    return None


def _update_heading_stack(
    heading_stack: list[tuple[int, str]],
    level: int,
    heading_text: str,
) -> None:
    while heading_stack and heading_stack[-1][0] >= level:
        heading_stack.pop()
    heading_stack.append((level, heading_text))


def chunk_markdown(cleaned_md: str, *, min_chars: int = 100) -> list[ChunkResult]:
    lines = cleaned_md.splitlines()
    chunks: list[ChunkResult] = []
    current_lines: list[str] = []
    current_parent: str | None = None
    heading_stack: list[tuple[int, str]] = []

    def close_chunk() -> None:
        nonlocal current_lines, current_parent
        text = _format_chunk_text(current_lines)
        if text:
            chunks.append(ChunkResult(chunk=text, parent_section_heading=current_parent))
        current_lines = []
        current_parent = None

    for line in lines:
        match = HEADING_PATTERN.match(line)
        if match:
            marker, heading_text = match.group(1), match.group(2).strip()
            level = _heading_level(marker)
            body_len = len(_normalize_chunk_text("\n".join(current_lines)))

            if current_lines and body_len >= min_chars:
                close_chunk()

            _update_heading_stack(heading_stack, level, heading_text)
            if not current_lines:
                current_parent = _parent_heading(heading_stack, level)
            current_lines.append(heading_text)
        else:
            current_lines.append(line)

    close_chunk()
    return chunks

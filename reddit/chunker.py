from __future__ import annotations

from reddit.client import MAX_FIRST_LEVEL_REPLIES
from reddit.models import RedditComment, RedditThread
from utils.markdown_chunker import ChunkResult


def chunk_reddit_thread(thread: RedditThread) -> list[ChunkResult]:
    chunks: list[ChunkResult] = []

    post_chunk = _format_post_chunk(thread)
    if post_chunk:
        chunks.append(ChunkResult(chunk=post_chunk, parent_section_heading=None))

    for comment in thread.comments:
        comment_chunk = _format_comment_chunk(comment)
        if comment_chunk:
            chunks.append(
                ChunkResult(chunk=comment_chunk, parent_section_heading=None)
            )

    return chunks


def _format_post_chunk(thread: RedditThread) -> str | None:
    title = thread.title.strip()
    body = thread.selftext.strip()
    parts: list[str] = []

    if title:
        parts.append(title)

    if body:
        parts.append(body)
    elif thread.link_url:
        parts.append(thread.link_url)

    if not parts:
        return None
    return "\n\n".join(parts).strip()


def _format_comment_chunk(comment: RedditComment) -> str | None:
    body = comment.body.strip()
    if not body:
        return None

    lines = [body]
    for reply in comment.replies[:MAX_FIRST_LEVEL_REPLIES]:
        reply_body = reply.body.strip()
        if reply_body:
            lines.append(f"> {reply_body}")

    return "\n\n".join(lines).strip()

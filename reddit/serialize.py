from __future__ import annotations

from typing import Any

from reddit.models import RedditComment, RedditThread


def to_storage_dict(thread: RedditThread) -> dict[str, Any]:
    return {
        "post_id": thread.post_id,
        "title": thread.title,
        "selftext": thread.selftext,
        "permalink": thread.permalink,
        "link_url": thread.link_url,
        "comments": [_comment_to_dict(c) for c in thread.comments],
    }


def from_storage_dict(data: dict[str, Any]) -> RedditThread:
    return RedditThread(
        post_id=data["post_id"],
        title=data.get("title") or "",
        selftext=data.get("selftext") or "",
        permalink=data.get("permalink") or "",
        link_url=data.get("link_url"),
        comments=[_comment_from_dict(c) for c in data.get("comments", [])],
    )


def _comment_to_dict(comment: RedditComment) -> dict[str, Any]:
    return {
        "body": comment.body,
        "replies": [_comment_to_dict(r) for r in comment.replies],
    }


def _comment_from_dict(data: dict[str, Any]) -> RedditComment:
    return RedditComment(
        body=data.get("body") or "",
        replies=[_comment_from_dict(r) for r in data.get("replies", [])],
    )

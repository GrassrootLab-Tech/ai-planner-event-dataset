from dataclasses import dataclass, field


@dataclass
class RedditComment:
    body: str
    replies: list["RedditComment"] = field(default_factory=list)


@dataclass
class RedditThread:
    post_id: str
    title: str
    selftext: str
    permalink: str
    link_url: str | None
    comments: list[RedditComment] = field(default_factory=list)

import re
from urllib.parse import urlparse

_REDDIT_HOSTS = {
    "reddit.com",
    "www.reddit.com",
    "old.reddit.com",
    "np.reddit.com",
    "m.reddit.com",
}

_POST_ID_PATTERN = re.compile(
    r"^/r/[^/]+/comments/(?P<post_id>[a-z0-9]+)/?",
    re.IGNORECASE,
)


def is_reddit_url(page_url: str) -> bool:
    host = urlparse(page_url).netloc.lower()
    if host in _REDDIT_HOSTS:
        return True
    return host.endswith(".reddit.com")


def is_reddit_post_url(page_url: str) -> bool:
    if not is_reddit_url(page_url):
        return False
    path = urlparse(page_url).path
    return _POST_ID_PATTERN.search(path) is not None


def extract_post_id(page_url: str) -> str:
    if not is_reddit_url(page_url):
        raise ValueError(f"Not a Reddit URL: {page_url}")
    path = urlparse(page_url).path
    match = _POST_ID_PATTERN.search(path)
    if match is None:
        raise ValueError(
            f"Not a Reddit post URL (expected /r/.../comments/{{id}}/...): {page_url}"
        )
    return match.group("post_id")

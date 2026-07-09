from urllib.parse import urlparse


def strip_trailing_slash(page_url: str) -> str:
    """Remove a trailing slash from a page URL, if present."""
    return page_url[:-1] if page_url.endswith("/") else page_url


def extract_website(page_url: str) -> str:
    """Return core website origin (scheme + host) without path or query params."""
    parsed = urlparse(page_url)
    return f"{parsed.scheme}://{parsed.netloc}"

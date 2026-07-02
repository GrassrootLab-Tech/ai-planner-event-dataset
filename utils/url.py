from urllib.parse import urlparse


def extract_website(page_url: str) -> str:
    """Return core website origin (scheme + host) without path or query params."""
    parsed = urlparse(page_url)
    return f"{parsed.scheme}://{parsed.netloc}"

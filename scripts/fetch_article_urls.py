"""Collect article URLs via SerpApi site: searches and append them to a file."""

from __future__ import annotations

import argparse
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Settings

SERPAPI_URL = "https://serpapi.com/search"
PAGE_SIZE = 10
DEFAULT_WORKERS = 8


def host_from_url(page_url: str) -> str:
    return urlparse(page_url.strip()).netloc


def load_hosts_from_sources(sources_path: Path) -> list[str]:
    hosts: list[str] = []
    seen: set[str] = set()
    for line in sources_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        host = host_from_url(line)
        if not host or host in seen:
            continue
        seen.add(host)
        hosts.append(host)
    return hosts


def load_existing_urls(output_path: Path) -> set[str]:
    if not output_path.exists():
        return set()
    return {
        line.strip()
        for line in output_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def fetch_top_links(api_key: str, host: str, keyword: str, top: int) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    start = 0

    with httpx.Client(timeout=60.0) as client:
        while len(links) < top:
            params = {
                "engine": "google",
                "q": f"site:{host} {keyword}",
                "api_key": api_key,
                "start": start,
            }
            response = client.get(SERPAPI_URL, params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("error"):
                raise RuntimeError(f"SerpApi error for {host}: {data['error']}")

            organic = data.get("organic_results") or []
            if not organic:
                break

            for result in organic:
                link = result.get("link")
                if not link or link in seen:
                    continue
                seen.add(link)
                links.append(link)
                if len(links) >= top:
                    break

            start += PAGE_SIZE

    return links


def append_urls(
    output_path: Path,
    urls: list[str],
    existing: set[str],
    lock: threading.Lock,
) -> int:
    with lock:
        new_urls = [url for url in urls if url not in existing]
        if not new_urls:
            return 0
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("a", encoding="utf-8") as f:
            for url in new_urls:
                f.write(url + "\n")
                existing.add(url)
        return len(new_urls)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect article URLs from SerpApi site: searches."
    )
    parser.add_argument("--keyword", required=True, help="Keyword after site:host")
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Top N organic results per site (default: 20)",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Single page/site URL for a one-host test run",
    )
    parser.add_argument(
        "--sources",
        default=str(ROOT / "scripts" / "sources.txt"),
        help="Batch input file of source URLs",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "scripts" / "article_urls.txt"),
        help="Append-only output file",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Thread pool size (default: {DEFAULT_WORKERS})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.top < 1:
        raise SystemExit("--top must be >= 1")
    if args.workers < 1:
        raise SystemExit("--workers must be >= 1")

    settings = Settings()
    if not settings.serpapi_api_key:
        raise SystemExit("SERPAPI_API_KEY is not set in the environment / .env")

    if args.url:
        host = host_from_url(args.url)
        if not host:
            raise SystemExit(f"Could not parse host from --url: {args.url}")
        hosts = [host]
    else:
        sources_path = Path(args.sources)
        if not sources_path.exists():
            raise SystemExit(f"Sources file not found: {sources_path}")
        hosts = load_hosts_from_sources(sources_path)
        if not hosts:
            raise SystemExit(f"No hosts found in {sources_path}")

    output_path = Path(args.output)
    existing = load_existing_urls(output_path)
    lock = threading.Lock()
    total_appended = 0
    total_hosts = len(hosts)

    print(
        f"Hosts: {total_hosts} | keyword={args.keyword!r} | "
        f"top={args.top} | workers={args.workers}"
    )

    def process_host(host: str) -> tuple[str, int, int]:
        links = fetch_top_links(
            settings.serpapi_api_key, host, args.keyword, args.top
        )
        appended = append_urls(output_path, links, existing, lock)
        return host, len(links), appended

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_host, host): host for host in hosts}
        done = 0
        for future in as_completed(futures):
            done += 1
            host = futures[future]
            try:
                host, got, appended = future.result()
                total_appended += appended
                print(f"[{done}/{total_hosts}] site:{host} got {got}, appended {appended}")
            except Exception as exc:
                print(f"[{done}/{total_hosts}] site:{host} failed: {exc}")

    print(f"Done. Newly appended: {total_appended} -> {output_path}")


if __name__ == "__main__":
    main()

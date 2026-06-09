import logging
import time
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

NEWS_SOURCES = ["bbc.com", "reuters.com", "aljazeera.com"]
MAX_CHARS_PER_SOURCE = 40_000   # increased — complex topics need more content
ARTICLES_PER_SOURCE = 2         # fetch top 2 articles per news domain
REQUEST_TIMEOUT = 15


def scrape_wikipedia(topic: str) -> Optional[str]:
    """Fetches full plain-text of a Wikipedia article via the MediaWiki API.
    Uses opensearch first to resolve the user's topic string to the correct page title.
    """
    t0 = time.time()
    try:
        # Step 1: find the best-matching Wikipedia page title
        search_resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "opensearch", "search": topic, "limit": 1, "format": "json"},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        search_resp.raise_for_status()
        search_results = search_resp.json()
        if not search_results[1]:
            logger.warning("No Wikipedia page found for: %s", topic)
            return None
        page_title = search_results[1][0]
        logger.info("Resolved '%s' → Wikipedia page: '%s'", topic, page_title)

        # Step 2: fetch the full article text using the resolved title
        resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "titles": page_title,
                "prop": "extracts",
                "explaintext": True,
                "redirects": 1,  # follow redirect pages to the real article
                "format": "json",
            },
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", {})
        text = next(iter(pages.values())).get("extract", "")
        if not text:
            logger.warning("Wikipedia returned no text for page: %s", page_title)
            return None
        elapsed = int((time.time() - t0) * 1000)
        logger.info("Wikipedia scraped in %dms (%d chars)", elapsed, len(text))
        return text[:MAX_CHARS_PER_SOURCE]
    except Exception as e:
        logger.error("Wikipedia scrape failed for '%s': %s", topic, e)
        return None


def _extract_text(html: str) -> str:
    """Pulls readable paragraph text from raw HTML, strips nav/scripts/ads."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    container = soup.find("article") or soup.find("main") or soup
    paragraphs = container.find_all("p")
    return " ".join(p.get_text(separator=" ", strip=True) for p in paragraphs)[:MAX_CHARS_PER_SOURCE]


def scrape_url(url: str) -> Optional[str]:
    """Fetches any URL and returns its main readable text."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        text = _extract_text(resp.text)
        if len(text) < 200:
            logger.warning("Too little text extracted from %s", url)
            return None
        return text
    except Exception as e:
        logger.error("Failed to scrape %s: %s", url, e)
        return None


def _duckduckgo_search(query: str, max_results: int = 1) -> list[str]:
    """Returns article URLs from a DuckDuckGo HTML search. No API key needed."""
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        urls = []
        for a in soup.select("a.result__a"):
            href = a.get("href", "")
            if "uddg=" in href:
                qs = parse_qs(urlparse(href).query)
                real_url = qs.get("uddg", [None])[0]
                if real_url:
                    urls.append(real_url)
            elif href.startswith("http"):
                urls.append(href)
            if len(urls) >= max_results:
                break
        return urls
    except Exception as e:
        logger.error("DuckDuckGo search failed: %s", e)
        return []


def scrape_news_source(source_domain: str, topic: str, description: str = "") -> Optional[str]:
    """Finds the top articles for a topic on a news domain and scrapes them.
    Uses description to surface articles covering the specific angles you care about.
    """
    t0 = time.time()

    # Build a richer query if a description was provided
    query_hint = ""
    if description:
        # Take first 80 chars of description as a search hint (truncate at word boundary)
        short = description[:80].rsplit(" ", 1)[0]
        query_hint = f" {short}"

    urls = _duckduckgo_search(
        f"site:{source_domain} {topic}{query_hint}",
        max_results=ARTICLES_PER_SOURCE,
    )
    if not urls:
        logger.warning("No results for '%s' on %s", topic, source_domain)
        return None

    texts = []
    for url in urls:
        time.sleep(1)
        text = scrape_url(url)
        if text:
            texts.append(text)

    if not texts:
        return None

    combined = "\n\n".join(texts)
    elapsed = int((time.time() - t0) * 1000)
    logger.info("%s scraped %d article(s) in %dms (%d chars)", source_domain, len(texts), elapsed, len(combined))
    return combined[:MAX_CHARS_PER_SOURCE]


def scrape_all(topic: str, description: str = "", seed_urls: list[str] = []) -> dict[str, str]:
    """
    Orchestrates all scraping for a context build (Pipeline A + C).
    Returns {source_name: text} for every source that succeeded.
    Total sources attempted: Wikipedia + 3 news domains + any seed URLs.
    description is used to steer news searches toward relevant angles.
    """
    t_total = time.time()
    results: dict[str, str] = {}

    logger.info("=== scrape_all started for: %s ===", topic)

    # 1. Wikipedia
    wiki_text = scrape_wikipedia(topic)
    if wiki_text:
        results["wikipedia"] = wiki_text

    # 2. Default news sources — pass description to enrich search queries
    for domain in NEWS_SOURCES:
        time.sleep(1)
        logger.info("Scraping %s", domain)
        text = scrape_news_source(domain, topic, description=description)
        if text:
            results[domain] = text

    # 3. Seed URLs provided by the user
    for url in seed_urls:
        time.sleep(1)
        logger.info("Scraping seed URL: %s", url)
        text = scrape_url(url)
        if text:
            results[url] = text

    total_elapsed = int((time.time() - t_total) * 1000)
    total_sources = 1 + len(NEWS_SOURCES) + len(seed_urls)
    logger.info(
        "=== scrape_all done: %d/%d sources in %dms ===",
        len(results), total_sources, total_elapsed,
    )
    return results

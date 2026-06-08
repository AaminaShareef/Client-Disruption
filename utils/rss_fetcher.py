"""
utils/rss_fetcher.py
====================
Source-type aware RSS fetcher for the Supply Chain Disruption
Intelligence System.

Public API
----------
fetch_articles_for_country(country)
    Fetches articles from all registered sources for a country
    (local + government + global wires).

fetch_articles_for_queries(queries, max_queries=15)
    Fires each query string as a Google News RSS search and returns
    the deduplicated article list.

Both functions return lists of article dicts in a normalised schema:

  {
    "title":       str,
    "url":         str,
    "published":   str,          # ISO-8601 or raw string
    "source":      str,          # outlet name
    "summary":     str,          # first 500 chars of description
    "trust_score": float,        # 0.0–1.0 from registry
    "category":    str,          # "local" | "government" | "global_wire" | "logistics" | "trade"
    "country":     str,          # country this source is linked to (may be "")
    "fetch_method": str          # "rss" | "google_news_rss"
  }

Internal deduplication is done by URL hash across both fetch
functions so callers can safely call both and extend a single list.
"""

import feedparser
import hashlib
import time
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from utils.rss_sources import (
    get_sources_for_country,
    build_gnews_url
)

# ==========================================
# LOGGING
# ==========================================

logger = logging.getLogger(__name__)

# ==========================================
# CONSTANTS
# ==========================================

REQUEST_TIMEOUT   = 12          # seconds per feed fetch
MAX_ARTICLES_PER_SOURCE = 15    # cap per source to prevent flooding
FETCH_DELAY       = 0.3         # polite delay between requests (seconds)
MAX_SUMMARY_CHARS = 500

# ==========================================
# DEDUPLICATION STORE
# (module-level; reset between analysis runs
#  by calling clear_seen_urls())
# ==========================================

_seen_urls: set[str] = set()


def clear_seen_urls():
    """Reset the dedup store. Call at the start of each /analyze run."""
    global _seen_urls
    _seen_urls = set()


def _url_key(url: str) -> str:
    """Stable hash of a URL for dedup."""
    return hashlib.md5(url.strip().lower().encode()).hexdigest()


# ==========================================
# DATE NORMALISER
# ==========================================

def _normalise_date(entry) -> str:
    """
    Try multiple feedparser date fields and return an ISO-8601 string.
    Falls back to current UTC time so downstream sort always works.
    """
    for field in ("published", "updated", "created"):
        raw = getattr(entry, field, None) or entry.get(field)
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                return dt.astimezone(timezone.utc).isoformat()
            except Exception:
                return raw   # return raw string rather than silently drop
    return datetime.now(timezone.utc).isoformat()


# ==========================================
# ARTICLE NORMALISER
# ==========================================

def _normalise_entry(
    entry,
    source_name: str,
    trust_score: float,
    category: str,
    country: str,
    fetch_method: str
) -> dict | None:
    """
    Convert a feedparser entry into the normalised article schema.
    Returns None if the entry has no usable URL.
    """
    url = (
        getattr(entry, "link", None)
        or entry.get("link", "")
        or ""
    ).strip()

    if not url:
        return None

    key = _url_key(url)
    if key in _seen_urls:
        return None
    _seen_urls.add(key)

    title = (
        getattr(entry, "title", None)
        or entry.get("title", "")
        or ""
    ).strip()

    raw_summary = (
        getattr(entry, "summary", None)
        or entry.get("summary", "")
        or getattr(entry, "description", None)
        or entry.get("description", "")
        or ""
    )
    # Strip any HTML tags crudely
    import re
    summary = re.sub(r"<[^>]+>", " ", raw_summary).strip()
    summary = " ".join(summary.split())[:MAX_SUMMARY_CHARS]

    return {
        "title":        title,
        "url":          url,
        "published":    _normalise_date(entry),
        "source":       source_name,
        "summary":      summary,
        "trust_score":  round(trust_score, 3),
        "category":     category,
        "country":      country,
        "fetch_method": fetch_method,
    }


# ==========================================
# CORE FETCHER
# ==========================================

def _fetch_feed(url: str, source_name: str, trust_score: float,
                category: str, country: str, fetch_method: str) -> list[dict]:
    """
    Fetch a single RSS/Atom feed URL and return normalised articles.
    Silently swallows network errors and logs a warning.
    """
    articles = []

    try:
        feed = feedparser.parse(
            url,
            agent="SupplyChainRiskBot/1.0",
            request_headers={"Accept": "application/rss+xml, application/xml, text/xml"}
        )

        # feedparser doesn't raise on HTTP errors — check status
        status = getattr(feed, "status", 200)
        if status >= 400:
            logger.warning(
                f"HTTP {status} fetching {source_name} | {url}"
            )
            return []

        if feed.bozo and not feed.entries:
            # bozo=True means malformed feed; skip if no entries parsed
            logger.warning(
                f"Bozo feed (malformed) skipped: {source_name}"
            )
            return []

        for entry in feed.entries[:MAX_ARTICLES_PER_SOURCE]:
            article = _normalise_entry(
                entry,
                source_name=source_name,
                trust_score=trust_score,
                category=category,
                country=country,
                fetch_method=fetch_method
            )
            if article:
                articles.append(article)

    except Exception as e:
        logger.warning(f"Fetch error [{source_name}]: {e}")

    return articles


# ==========================================
# PUBLIC: fetch_articles_for_country
# ==========================================

def fetch_articles_for_country(country: str) -> list[dict]:
    """
    Fetch all articles for a country using its registered sources
    (local + government + global wires + logistics).

    Returns a deduplicated list of normalised article dicts.
    """
    sources  = get_sources_for_country(country)
    articles = []

    for source in sources:
        name         = source.get("name",        "Unknown Source")
        url          = source.get("url",          "")
        trust_score  = source.get("trust_score",  0.65)
        category     = source.get("category",     "unknown")
        fetch_method = source.get("type",         "rss")

        if not url:
            continue

        batch = _fetch_feed(
            url          = url,
            source_name  = name,
            trust_score  = trust_score,
            category     = category,
            country      = country,
            fetch_method = fetch_method
        )
        articles.extend(batch)

        if batch:
            time.sleep(FETCH_DELAY)

    logger.info(
        f"[{country}] Fetched {len(articles)} articles "
        f"from {len(sources)} sources"
    )
    return articles


# ==========================================
# PUBLIC: fetch_articles_for_queries
# ==========================================

def fetch_articles_for_queries(
    queries: list[str],
    max_queries: int = 15
) -> list[dict]:
    """
    Fire each query string as a Google News RSS search.

    Queries are the three-prong strings from generate_queries().
    We cap at max_queries to avoid rate-limiting; the caller should
    pass the highest-priority queries first (entity prongs first,
    then geo, then commodity).

    Returns a deduplicated list of normalised article dicts.
    """
    articles = []

    for query in queries[:max_queries]:
        url = build_gnews_url(query)

        batch = _fetch_feed(
            url          = url,
            source_name  = f"Google News: {query[:60]}",
            trust_score  = 0.70,   # conservative default for GNews
            category     = "google_news",
            country      = "",     # no single country for query results
            fetch_method = "google_news_rss"
        )
        articles.extend(batch)

        if batch:
            time.sleep(FETCH_DELAY)

    logger.info(
        f"[Queries] Fetched {len(articles)} articles "
        f"from {min(len(queries), max_queries)} queries"
    )
    return articles
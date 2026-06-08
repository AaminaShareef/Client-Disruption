"""
utils/newsapi_fetcher.py
========================
NewsAPI.org fetcher for the Supply Chain Disruption Intelligence System.

Wraps the /v2/everything endpoint and returns articles in the same
normalised schema used by rss_fetcher.py so the two sources can be
merged and scored identically downstream.

Normalised article schema
--------------------------
{
    "title":        str,
    "url":          str,
    "published":    str,   # ISO-8601
    "source":       str,   # outlet name
    "summary":      str,   # first 500 chars of description
    "trust_score":  float, # 0.0–1.0
    "category":     str,   # always "newsapi"
    "country":      str,   # country context (may be "")
    "fetch_method": str,   # always "newsapi"
}

Public API
----------
fetch_newsapi_for_queries(queries, max_queries, country_hint)
    Fire each query string against NewsAPI /v2/everything and
    return a deduplicated list of normalised articles.

fetch_newsapi_for_country(country)
    Fire a broad country-level disruption query to catch anything
    missed by the geo-prong queries.

Configuration (all via .env)
-----------------------------
NEWSAPI_KEY          — required; your NewsAPI.org API key
NEWSAPI_PAGE_SIZE    — optional; articles per request (default 10, max 100)
NEWSAPI_LANGUAGE     — optional; ISO 639-1 code (default "en")
NEWSAPI_SORT_BY      — optional; relevancy | popularity | publishedAt (default publishedAt)
NEWSAPI_FROM_DAYS    — optional; look-back window in days (default 3)
"""

import hashlib
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# LOGGING
# ==========================================

logger = logging.getLogger(__name__)

# ==========================================
# CONFIG
# ==========================================

_API_KEY      = os.getenv("NEWSAPI_KEY", "")
_BASE_URL     = "https://newsapi.org/v2/everything"
_PAGE_SIZE    = int(os.getenv("NEWSAPI_PAGE_SIZE",  "10"))
_LANGUAGE     = os.getenv("NEWSAPI_LANGUAGE",       "en")
_SORT_BY      = os.getenv("NEWSAPI_SORT_BY",        "publishedAt")
_FROM_DAYS    = int(os.getenv("NEWSAPI_FROM_DAYS",  "3"))
_REQUEST_TIMEOUT = 15   # seconds
_FETCH_DELAY     = 0.5  # polite delay between requests (seconds)
_MAX_SUMMARY_CHARS = 500

# NewsAPI free tier caps: 100 requests/day, 100 results/request
# Developer tier caps:    500 requests/day
# We default to 10 articles/query so callers can fire more queries
# within the daily budget.

# ==========================================
# DEDUPLICATION STORE
# (shared with rss_fetcher via caller passing in the same set,
#  or used standalone — module-level store is fine for now)
# ==========================================

_seen_urls: set[str] = set()


def clear_seen_urls() -> None:
    """Reset the dedup store. Call at the start of each /analyze run."""
    global _seen_urls
    _seen_urls = set()


def _url_key(url: str) -> str:
    return hashlib.md5(url.strip().lower().encode()).hexdigest()


# ==========================================
# DATE HELPERS
# ==========================================

def _iso_from_days_ago(days: int) -> str:
    """Return an ISO-8601 date string N days before now (UTC)."""
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalise_date(raw: str) -> str:
    """
    NewsAPI returns ISO-8601 strings like '2024-01-15T12:30:00Z'.
    Pass through if valid, else return current UTC.
    """
    if raw:
        try:
            # Validate by parsing; re-emit canonical form
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            return raw
    return datetime.now(timezone.utc).isoformat()


# ==========================================
# ARTICLE NORMALISER
# ==========================================

def _normalise_article(
    item: dict,
    country: str = "",
    trust_score: float = 0.72,
) -> dict | None:
    """
    Convert a NewsAPI article object into the normalised schema.
    Returns None if the article has no usable URL or is removed.
    """
    url = (item.get("url") or "").strip()
    if not url or url == "https://removed.com":
        return None

    key = _url_key(url)
    if key in _seen_urls:
        return None
    _seen_urls.add(key)

    title = (item.get("title") or "").strip()
    if not title or title == "[Removed]":
        return None

    # NewsAPI description field → summary
    raw_desc = item.get("description") or item.get("content") or ""
    # Truncate content field which NewsAPI cuts at 200 chars anyway
    import re
    summary = re.sub(r"<[^>]+>", " ", raw_desc).strip()
    summary = " ".join(summary.split())[:_MAX_SUMMARY_CHARS]

    # Source name from nested dict
    source_name = ""
    src = item.get("source")
    if isinstance(src, dict):
        source_name = src.get("name") or src.get("id") or ""
    elif isinstance(src, str):
        source_name = src

    published = _normalise_date(item.get("publishedAt", ""))

    return {
        "title":        title,
        "url":          url,
        "published":    published,
        "source":       source_name,
        "summary":      summary,
        "trust_score":  round(trust_score, 3),
        "category":     "newsapi",
        "country":      country,
        "fetch_method": "newsapi",
    }


# ==========================================
# CORE REQUEST WRAPPER
# ==========================================

def _call_newsapi(params: dict) -> list[dict]:
    """
    Make one call to /v2/everything and return the raw articles list.
    Returns [] on any error (network, auth, rate-limit).
    """
    if not _API_KEY:
        logger.warning(
            "NEWSAPI_KEY not set — skipping NewsAPI fetch. "
            "Add it to your .env file."
        )
        return []

    headers = {"X-Api-Key": _API_KEY}

    try:
        resp = requests.get(
            _BASE_URL,
            params=params,
            headers=headers,
            timeout=_REQUEST_TIMEOUT
        )

        if resp.status_code == 401:
            logger.error("NewsAPI: invalid API key (401). Check NEWSAPI_KEY in .env.")
            return []

        if resp.status_code == 426:
            logger.warning("NewsAPI: upgrade required (426) — developer plan needed for this query.")
            return []

        if resp.status_code == 429:
            logger.warning("NewsAPI: rate limited (429) — too many requests today.")
            return []

        if resp.status_code != 200:
            logger.warning(f"NewsAPI: HTTP {resp.status_code} — {resp.text[:200]}")
            return []

        data = resp.json()

        if data.get("status") != "ok":
            code = data.get("code", "unknown")
            msg  = data.get("message", "")
            logger.warning(f"NewsAPI error [{code}]: {msg}")
            return []

        return data.get("articles", [])

    except requests.exceptions.Timeout:
        logger.warning("NewsAPI: request timed out.")
        return []
    except requests.exceptions.ConnectionError as e:
        logger.warning(f"NewsAPI: connection error — {e}")
        return []
    except Exception as e:
        logger.warning(f"NewsAPI: unexpected error — {e}")
        return []


# ==========================================
# TRUST SCORE HEURISTICS
# ==========================================

# Known high-trust supply chain / trade outlets and their scores.
# Anything not in this list gets the conservative default (0.70).
_OUTLET_TRUST: dict[str, float] = {
    # Tier 1 — specialist supply chain / trade press
    "freightwaves":             0.92,
    "supplychaindive":          0.91,
    "joc.com":                  0.90,
    "lloydslist":               0.90,
    "tradewindsnews":           0.88,
    "agpublications":           0.87,
    "semiconductorintelligence": 0.88,
    "electronicsnews":          0.85,
    "mining.com":               0.85,
    # Tier 2 — major wires / business press
    "reuters":                  0.90,
    "bloomberg":                0.89,
    "financial times":          0.88,
    "the wall street journal":  0.87,
    "nikkei":                   0.87,
    "south china morning post": 0.84,
    "associated press":         0.88,
    "agence france-presse":     0.87,
    # Tier 3 — broad business press
    "the guardian":             0.82,
    "bbc news":                 0.83,
    "cnbc":                     0.78,
    "forbes":                   0.72,
    "techcrunch":               0.74,
}


def _trust_for_source(source_name: str) -> float:
    """Return a trust score for a NewsAPI source name."""
    name_lower = source_name.lower()
    for outlet, score in _OUTLET_TRUST.items():
        if outlet in name_lower:
            return score
    return 0.70   # conservative default


# ==========================================
# PUBLIC: fetch_newsapi_for_queries
# ==========================================

def fetch_newsapi_for_queries(
    queries: list[str],
    max_queries: int = 10,
    country_hint: str = "",
) -> list[dict]:
    """
    Fire each query string against NewsAPI /v2/everything.

    The query strings come from generate_queries() in query_generator.py.
    They contain boolean AND/OR and quoted phrases — NewsAPI supports
    this syntax natively (up to 500 chars per query).

    Parameters
    ----------
    queries      : list of query strings from generate_queries()
    max_queries  : cap to stay within daily API budget (default 10)
    country_hint : optional country string to tag articles (cosmetic)

    Returns
    -------
    Deduplicated list of normalised article dicts, sorted newest first.
    """
    articles: list[dict] = []
    from_date = _iso_from_days_ago(_FROM_DAYS)

    for query in queries[:max_queries]:
        # NewsAPI query length limit is 500 chars
        q = query[:500]

        params = {
            "q":          q,
            "language":   _LANGUAGE,
            "sortBy":     _SORT_BY,
            "pageSize":   _PAGE_SIZE,
            "from":       from_date,
        }

        raw_items = _call_newsapi(params)

        for item in raw_items:
            source_name = ""
            src = item.get("source")
            if isinstance(src, dict):
                source_name = src.get("name") or ""
            trust = _trust_for_source(source_name)

            article = _normalise_article(
                item,
                country=country_hint,
                trust_score=trust,
            )
            if article:
                articles.append(article)

        if raw_items:
            time.sleep(_FETCH_DELAY)

    logger.info(
        f"[NewsAPI/queries] Fetched {len(articles)} articles "
        f"from {min(len(queries), max_queries)} queries"
    )
    return articles


# ==========================================
# PUBLIC: fetch_newsapi_for_country
# ==========================================

# Disruption terms broad enough to catch country-level signals
# without being too narrow (these are ORed together)
_COUNTRY_DISRUPTION_TERMS = [
    "supply chain", "factory", "port", "logistics", "strike",
    "flood", "earthquake", "sanctions", "shortage", "disruption",
    "tariff", "export ban", "conflict",
]


def fetch_newsapi_for_country(country: str) -> list[dict]:
    """
    Fetch disruption news for a country using a broad NewsAPI query.

    Builds a query like:
        "{country}" AND (supply chain OR factory OR port OR ... )

    This acts as a catch-all for country-level signals that the
    three-prong geo queries might miss (e.g. novel disruption types).

    Returns a deduplicated list of normalised article dicts.
    """
    terms_str = " OR ".join(f'"{t}"' for t in _COUNTRY_DISRUPTION_TERMS)
    query     = f'"{country}" AND ({terms_str})'
    query     = query[:500]

    from_date = _iso_from_days_ago(_FROM_DAYS)

    params = {
        "q":        query,
        "language": _LANGUAGE,
        "sortBy":   _SORT_BY,
        "pageSize": _PAGE_SIZE,
        "from":     from_date,
    }

    raw_items = _call_newsapi(params)
    articles  = []

    for item in raw_items:
        source_name = ""
        src = item.get("source")
        if isinstance(src, dict):
            source_name = src.get("name") or ""
        trust = _trust_for_source(source_name)

        article = _normalise_article(
            item,
            country=country,
            trust_score=trust,
        )
        if article:
            articles.append(article)

    logger.info(
        f"[NewsAPI/{country}] Fetched {len(articles)} articles"
    )
    return articles
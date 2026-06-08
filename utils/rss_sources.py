"""
utils/rss_sources.py
====================
Loads geography_registry.json and exposes two public helpers:

  get_sources_for_country(country)
      Returns the combined source list (local + government + global
      defaults) for a country, each entry guaranteed to have a
      trust_score.

  build_gnews_url(query)
      Converts a plain-text query string into a Google News RSS URL
      so the rss_fetcher can fire entity / geo / commodity prongs
      directly against Google News without touching NewsAPI.
"""

import json
import os
import urllib.parse

# ==========================================
# REGISTRY PATH
# ==========================================

_REGISTRY_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "data",
    "geography_registry.json"
)

_registry = None


def _load_registry():
    global _registry
    if _registry is None:
        with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
            _registry = json.load(f)
    return _registry


# ==========================================
# PUBLIC: get_sources_for_country
# ==========================================

def get_sources_for_country(country: str) -> list[dict]:
    """
    Return an ordered source list for a country.

    Order: local → government → global_wire → logistics
    Each entry has: name, type, url, trust_score, category

    Falls back to global defaults only if the country has no entry
    in the registry.
    """
    reg      = _load_registry()
    defaults = reg.get("defaults", {})
    countries = reg.get("countries", {})

    sources = []
    seen_urls = set()

    def _add(src_list):
        for s in src_list:
            url = s.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                # Guarantee trust_score exists
                entry = dict(s)
                entry.setdefault("trust_score", 0.65)
                sources.append(entry)

    # Country-specific sources first
    country_data = countries.get(country, {})
    _add(country_data.get("local",      []))
    _add(country_data.get("government", []))

    # Always append global wires and logistics sources
    _add(defaults.get("global_wire_sources", []))
    _add(defaults.get("logistics_sources",   []))

    return sources


# ==========================================
# PUBLIC: build_gnews_url
# ==========================================

def build_gnews_url(query: str, lang: str = "en") -> str:
    """
    Build a Google News RSS search URL from a query string.

    Google News RSS search format:
      https://news.google.com/rss/search?q=<encoded>&hl=en-US&gl=US&ceid=US:en

    The query is URL-encoded; boolean operators (AND, OR, NOT) and
    quoted phrases are preserved correctly by urllib.parse.quote.
    """
    encoded = urllib.parse.quote(query, safe='')
    return (
        f"https://news.google.com/rss/search"
        f"?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    )
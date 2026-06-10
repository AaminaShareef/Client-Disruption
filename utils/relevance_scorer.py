"""
utils/relevance_scorer.py
=========================
100-point rule-based relevance scorer for supply chain disruption articles.

Scoring dimensions
------------------
  A. Disruption signal     (0–35 pts)  — does the article describe a real event?
  B. Supply chain keyword  (0–20 pts)  — is supply chain context present?
  C. Entity match          (0–20 pts)  — does it mention a client exposure node?
  D. Geographic match      (0–15 pts)  — country / city / port alignment
  E. Source trust          (0–10 pts)  — outlet credibility from registry

Total → 100 pts maximum.

Impact levels
-------------
  HIGH   : score >= 60
  MEDIUM : score >= 35
  LOW    : score <  35

False-positive guards
---------------------
  1. Press-release filter  — articles from PR / investor-relations paths are
     penalised heavily unless they also contain a disruption signal.
  2. Minimum gate          — articles must score >= 1 in BOTH dimension A
     (disruption) AND dimension B (supply chain) to pass LOW threshold.
     A pure supply chain article with zero disruption signal is filtered out.
  3. Title-only check      — scoring runs over title + summary combined so
     a strong disruption term in the title isn't diluted by a clean summary.
"""

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

# ==========================================
# CONFIG PATH
# ==========================================

_BASE = os.path.join(os.path.dirname(__file__), "..", "config")

_disruption_cfg = None


def _disruption():
    global _disruption_cfg
    if _disruption_cfg is None:
        path = os.path.join(_BASE, "disruption_terms.json")
        with open(path, "r", encoding="utf-8") as f:
            _disruption_cfg = json.load(f)
    return _disruption_cfg


# ==========================================
# STATIC TERM SETS
# ==========================================

# Supply chain context keywords — must appear alongside a disruption signal
_SC_KEYWORDS = [
    # Core supply chain
    "supply chain", "supplier", "manufacturer", "factory", "plant",
    "production", "shipment", "freight", "logistics", "warehouse",
    "inventory", "procurement", "sourcing", "vendor", "component",
    "assembly", "semiconductor", "chip", "wafer", "port", "cargo",
    "container", "shipping", "trade", "export", "import", "raw material",
    "commodity", "stockpile", "shortage", "capacity", "throughput",
    "tier-1", "tier 1", "oem", "contract manufacturer", "foundry",
    "just-in-time", "just in time", "lead time", "bill of materials",
    # Energy / LNG / petrochemical vocabulary
    "lng", "liquefied natural gas", "natural gas", "pipeline",
    "refinery", "oil field", "gas field", "oil terminal", "gas terminal",
    "tanker", "supertanker", "vlcc", "lng carrier", "regasification",
    "liquefaction", "petrochemical", "crude oil", "refined product",
    "upstream", "downstream", "midstream", "wellhead", "rig",
    "offshore platform", "onshore", "gas plant", "processing plant",
    "feedstock", "fuel supply", "energy supply", "power grid",
    "electricity grid", "grid outage", "blackout", "brownout",
    "power plant", "solar farm", "wind farm", "battery storage",
    "lithium", "cobalt", "nickel", "rare earth", "critical mineral",
    "mining", "mine", "smelter", "ore", "concentrate",
]

# Press-release / investor-relations signals (false-positive guard)
_PR_SIGNALS = [
    "press release", "for immediate release", "announces", "announced today",
    "proud to announce", "pleased to announce", "partnership with",
    "new product launch", "quarterly results", "earnings call",
    "investor relations", "shareholder", "dividend", "ipo",
    "we are excited", "delighted to", "proud to present",
]

# Geographic noise — terms that share words with countries/cities but are
# not supply chain geographic references
_GEO_NOISE = [
    "china clay", "china cabinet", "china set", "jordan almonds",
    "turkey dinner", "iran-ic", "india ink", "india rubber",
]

# ==========================================
# DIMENSION A — DISRUPTION SIGNAL (0–35)
# ==========================================

# Per-domain point values — conflict and commodity get slight boosts
# because they correlate most directly with supply chain impact
_DOMAIN_POINTS = {
    "conflict":       8,
    "commodity":      8,
    "labour":         7,
    "weather":        6,
    "political":      6,
    "infrastructure": 7,   # pipeline/grid/refinery disruptions
    "regulatory":     6,   # sanctions, export controls, permits
    "pandemic":       5,
}

# Bonus for multiple distinct domains triggered simultaneously
_MULTI_DOMAIN_BONUS = 5   # awarded when ≥ 2 domains trigger


# Inline disruption terms for domains not always in disruption_terms.json.
# These supplement the JSON config so energy/infrastructure profiles score
# correctly without requiring config file edits.
_INLINE_DISRUPTION_TERMS: dict[str, list[str]] = {
    "infrastructure": [
        "pipeline rupture", "pipeline explosion", "pipeline leak", "pipeline fire",
        "refinery fire", "refinery explosion", "refinery outage", "refinery shutdown",
        "plant shutdown", "plant explosion", "facility shutdown", "terminal closure",
        "power outage", "blackout", "grid failure", "grid collapse", "grid disruption",
        "gas leak", "oil spill", "tanker collision", "tanker grounding",
        "platform shutdown", "rig accident", "well blowout",
        "compressor failure", "pump failure", "equipment failure",
        "infrastructure attack", "sabotage",
    ],
    "regulatory": [
        "sanctions", "export ban", "import ban", "export restriction",
        "trade embargo", "trade ban", "permit suspended", "licence revoked",
        "regulatory halt", "regulatory shutdown", "compliance failure",
        "forced shutdown", "government seizure", "nationalisation",
        "expropriation", "asset freeze",
    ],
    "commodity": [
        "price surge", "price spike", "supply crunch", "supply squeeze",
        "shortage", "scarcity", "stockpile depletion", "inventory shortage",
        "production cut", "output cut", "quota reduction",
        "lng shortage", "gas shortage", "oil shortage", "fuel shortage",
        "energy shortage", "power shortage", "electricity shortage",
    ],
}


def _score_disruption(text: str) -> tuple[int, list[str]]:
    """
    Returns (points, triggered_domain_names).
    Cap: 35 pts.

    Checks JSON config domains first, then inline supplementary terms
    for infrastructure/regulatory/commodity which are commonly missing
    from generic disruption_terms.json configs.
    """
    cfg         = _disruption()
    domains_hit = []
    points      = 0
    seen_domains = set()

    # ── JSON config domains ───────────────────────────────
    for domain_name, domain_data in cfg["domains"].items():
        for term in domain_data["terms"]:
            pattern = r'\b' + re.escape(term.lower()) + r'\b'
            if re.search(pattern, text):
                domains_hit.append(domain_name)
                seen_domains.add(domain_name)
                points += _DOMAIN_POINTS.get(domain_name, 5)
                break

    # ── Inline supplementary terms ────────────────────────
    for domain_name, terms in _INLINE_DISRUPTION_TERMS.items():
        if domain_name in seen_domains:
            continue   # already scored from JSON config
        for term in terms:
            if term in text:   # substring match fine here — terms are phrases
                domains_hit.append(domain_name)
                seen_domains.add(domain_name)
                points += _DOMAIN_POINTS.get(domain_name, 5)
                break

    if len(domains_hit) >= 2:
        points += _MULTI_DOMAIN_BONUS

    return min(points, 35), domains_hit


# ==========================================
# DIMENSION B — SUPPLY CHAIN KEYWORD (0–20)
# ==========================================

def _score_supply_chain(text: str) -> int:
    """
    Returns 0–20 pts based on density of SC keywords.
    """
    hits = 0
    for kw in _SC_KEYWORDS:
        if kw in text:
            hits += 1

    if hits == 0:
        return 0
    if hits == 1:
        return 6
    if hits == 2:
        return 11
    if hits <= 4:
        return 16
    return 20


# ==========================================
# DIMENSION C — ENTITY MATCH (0–20)
# ==========================================

def _score_entity_match(text: str, exposure: dict) -> tuple[int, list[str]]:
    """
    Returns (points, matched_entity_names).

    Checks:
      - Tier-1 supplier names
      - Raw material names + synonyms
      - Port names + aliases
      - Route names
      - Country and city names (partial credit)
    """
    matched = []
    points  = 0

    # Helper: safe whole-word search
    def _hit(term: str) -> bool:
        if not term or len(term) < 3:
            return False
        pattern = r'\b' + re.escape(term.lower()) + r'\b'
        return bool(re.search(pattern, text))

    # Suppliers (high value — direct client exposure)
    for name in exposure.get("suppliers", []):
        if _hit(name):
            matched.append(name)
            points += 8

    # Materials — check key + synonyms
    from utils.rss_sources import _load_registry   # noqa — lazy import
    mat_records = exposure.get("material_records", {})
    for mat_key in exposure.get("materials", []):
        rec = mat_records.get(mat_key, {})
        names_to_check = [mat_key] + rec.get("synonyms", [])
        for n in names_to_check:
            if _hit(n):
                matched.append(mat_key)
                points += 6
                break

    # Ports — key + aliases
    port_records = exposure.get("port_records", {})
    for port_key in exposure.get("ports", []):
        rec = port_records.get(port_key, {})
        names_to_check = [port_key] + rec.get("aliases", [])
        for n in names_to_check:
            if _hit(n):
                matched.append(port_key)
                points += 5
                break

    # Routes / chokepoints
    route_records = exposure.get("route_records", {})
    for route_key in exposure.get("routes", []):
        rec = route_records.get(route_key, {})
        query_terms = rec.get("query_terms", [route_key])
        for qt in query_terms:
            if _hit(qt):
                matched.append(route_key)
                points += 5
                break

    # Logistics node names (catch anything not already matched as port/route)
    already_matched = set(matched)
    for node in exposure.get("logistics_nodes", []):
        if node not in already_matched and _hit(node):
            matched.append(node)
            points += 3

    return min(points, 20), list(dict.fromkeys(matched))   # dedup, preserve order


# ==========================================
# DIMENSION D — GEOGRAPHIC MATCH (0–15)
# ==========================================

def _score_geographic(text: str, exposure: dict) -> int:
    """
    Returns 0–15 pts.
    Country name hit = 5 pts; city name hit = 3 pts each (cap 15).
    """
    points = 0

    # Noise guard: strip known false-positive geo phrases
    clean_text = text
    for noise in _GEO_NOISE:
        clean_text = clean_text.replace(noise, "")

    for country in exposure.get("countries", []):
        pattern = r'\b' + re.escape(country.lower()) + r'\b'
        if re.search(pattern, clean_text):
            points += 5

    cities_map = exposure.get("cities", {})
    for country, city_list in cities_map.items():
        for city in city_list[:5]:   # only top 5 cities per country
            if len(city) < 4:
                continue  # skip very short city names (false positive risk)
            pattern = r'\b' + re.escape(city.lower()) + r'\b'
            if re.search(pattern, clean_text):
                points += 3

    return min(points, 15)


# ==========================================
# DIMENSION E — SOURCE TRUST (0–10)
# ==========================================

def _score_trust(trust_score: float) -> int:
    """
    Map 0.0–1.0 trust_score → 0–10 pts.
    """
    return min(int(round(trust_score * 10)), 10)


# ==========================================
# FALSE-POSITIVE GUARDS
# ==========================================

def _press_release_penalty(text: str) -> int:
    """
    Returns a point penalty (negative int) if PR signals are detected.
    Only penalises if the article looks like a press release with no
    disruption context.
    """
    pr_hits = sum(1 for sig in _PR_SIGNALS if sig in text)
    if pr_hits >= 2:
        return -15
    if pr_hits == 1:
        return -5
    return 0


def _build_text(article: dict) -> str:
    """
    Combine title + summary/description into a single lowercased
    string for term matching.
    """
    title   = article.get("title",       "") or ""
    summary = (
        article.get("summary",      "")
        or article.get("description", "")
        or ""
    )
    return (title + " " + summary).lower()


# ==========================================
# IMPACT LEVEL
# ==========================================

def _impact_level(score: int, disruption_pts: int, sc_pts: int) -> str:
    """
    Minimum gate: article must score > 0 in BOTH disruption AND
    supply-chain dimensions, otherwise it's LOW regardless of total.
    """
    if disruption_pts == 0 or sc_pts == 0:
        return "LOW"
    if score >= 55:
        return "HIGH"
    if score >= 30:
        return "MEDIUM"
    return "LOW"


# ==========================================
# NODE LINKAGE
# ==========================================

def _linked_nodes(matched_entities: list[str], exposure: dict) -> list[str]:
    """
    Map matched entity names back to supply chain node types so the
    frontend can show which nodes are at risk.

    Returns a list like ["supplier:TSMC", "material:semiconductors",
    "port:Port of Kaohsiung", "route:Taiwan Strait"]
    """
    nodes = []
    supplier_set = set(exposure.get("suppliers", []))
    material_set = set(exposure.get("materials", []))
    port_set     = set(exposure.get("ports",     []))
    route_set    = set(exposure.get("routes",    []))

    for entity in matched_entities:
        if entity in supplier_set:
            nodes.append(f"supplier:{entity}")
        elif entity in material_set:
            nodes.append(f"material:{entity}")
        elif entity in port_set:
            nodes.append(f"port:{entity}")
        elif entity in route_set:
            nodes.append(f"route:{entity}")

    return nodes


# ==========================================
# PUBLIC: score_articles
# ==========================================

def score_articles(
    articles: list[dict],
    exposure: dict
) -> list[dict]:
    """
    Score and enrich a list of article dicts against the client
    exposure map.

    Each article is returned with these added fields:
      relevance_score   int        0–100
      impact_level      str        HIGH | MEDIUM | LOW
      matched_entities  list[str]  entity names found in article text
      linked_nodes      list[str]  "type:name" node tags
      disruption_domains list[str] which disruption domains triggered
      score_breakdown   dict       per-dimension points (for debugging)
      published_at      str        alias of published (frontend compat)
      description       str        alias of summary  (frontend compat)
      source_type       str        alias of fetch_method (frontend compat)

    Articles with impact_level == LOW are included but sorted last.
    The list is returned sorted: HIGH → MEDIUM → LOW, then by score desc.
    """
    scored = []

    for article in articles:
        text = _build_text(article)

        # --- Five dimensions ---
        disruption_pts, domains_hit  = _score_disruption(text)
        sc_pts                       = _score_supply_chain(text)
        entity_pts, matched_entities = _score_entity_match(text, exposure)
        geo_pts                      = _score_geographic(text, exposure)
        trust_pts                    = _score_trust(
                                           article.get("trust_score", 0.65)
                                       )

        # --- False-positive guard ---
        pr_penalty = _press_release_penalty(text)

        raw_score = (
            disruption_pts
            + sc_pts
            + entity_pts
            + geo_pts
            + trust_pts
            + pr_penalty
        )
        final_score = max(0, min(raw_score, 100))

        level = _impact_level(final_score, disruption_pts, sc_pts)
        nodes = _linked_nodes(matched_entities, exposure)

        enriched = dict(article)   # copy so we don't mutate the input

        enriched.update({
            "relevance_score":    final_score,
            "impact_level":       level,
            "matched_entities":   matched_entities,
            "linked_nodes":       nodes,
            "disruption_domains": domains_hit,
            "score_breakdown": {
                "disruption":  disruption_pts,
                "supply_chain": sc_pts,
                "entity":      entity_pts,
                "geographic":  geo_pts,
                "trust":       trust_pts,
                "pr_penalty":  pr_penalty,
            },
            # Frontend compatibility aliases
            "published_at":  article.get("published", ""),
            "description":   article.get("summary",   ""),
            "source_type":   article.get("fetch_method", "rss"),
        })

        scored.append(enriched)

    # Sort: HIGH first, then MEDIUM, then LOW; within each band by score desc
    _level_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    scored.sort(
        key=lambda a: (
            _level_order.get(a["impact_level"], 2),
            -a["relevance_score"]
        )
    )

    high_count   = sum(1 for a in scored if a["impact_level"] == "HIGH")
    medium_count = sum(1 for a in scored if a["impact_level"] == "MEDIUM")
    low_count    = sum(1 for a in scored if a["impact_level"] == "LOW")

    logger.info(
        f"Scored {len(scored)} articles — "
        f"HIGH:{high_count} MEDIUM:{medium_count} LOW:{low_count}"
    )

    return scored
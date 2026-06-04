"""
app.py — Supply Chain Risk Intelligence Dashboard  (v8 — Precision Filtering)
===============================================================================

FIXES IN v8 (over v7):
───────────────────────

1. SUPPLIER ALIASES NO LONGER INCLUDE GENERIC MATERIAL WORDS
   v7 put "semiconductor", "chip", "foundry" in TSMC/Samsung alias lists.
   Any article mentioning those words (Canadian startup awards, EU policy
   statements) matched a supplier. v8 aliases for suppliers contain ONLY
   the company name and location variants (tsmc, taiwan semiconductor,
   hsinchu fab, etc.). Generic material words are removed entirely.

2. POSITIVE_ONLY_SIGNALS MASSIVELY EXPANDED
   v7 missed: award ceremonies, government grants, policy welcomes,
   partnership announcements. v8 adds: "receives award", "wins award",
   "awarded grant", "chips award", "letter of intent", "welcomed the",
   "pleased to announce", "today announced", "deepens collaboration",
   "distribution agreement", and more.

3. IMPACT CLASSIFIER NOW CHECKS PROXIMITY
   classify_impact() now accepts the entity keyword set. CRITICAL/HIGH
   are only assigned when the disruption signal appears within 120
   characters of an entity-relevant keyword. "Europe Must Turn
   Semiconductor Ambition Into Reality" no longer gets CRITICAL.

4. JSON ALWAYS OVERWRITES (no stale accumulation)
   v7 appended articles to the existing daily file. v8 always writes
   only the current run's articles. Run history is preserved in 'runs'.
"""

import re, json, hashlib, unicodedata, feedparser
from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta
from pathlib import Path


app = Flask(__name__)
app.secret_key = "scri-2024-key"


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — GLOBAL CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

DAYS_BACK       = 14   # look-back window
MAX_PER_ENTITY  = 5    # max articles per entity
MAX_FINAL       = 15   # max articles in final response
MIN_HITS        = 3    # RAISED from 2 → 3: requires stronger keyword overlap

DATA_DIR = Path("data/news")
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — RSS FEED REGISTRY
# ══════════════════════════════════════════════════════════════════════════════

RSS_FEEDS = {
    "logistics": [
        "https://www.freightwaves.com/news/feed",
        "https://www.supplychaindive.com/feeds/news/",
        "https://www.joc.com/rss/all",
        "https://lloydslist.maritimeintelligence.informa.com/rss",
        "https://www.maritimeexecutive.com/rss",
        "https://splash247.com/feed/",
        "https://theloadstar.com/feed/",
        "https://www.hellenicshippingnews.com/feed/",
        "https://www.tradewindsnews.com/rss",
    ],
    "geopolitics": [
        "https://feeds.reuters.com/reuters/businessNews",
        "https://feeds.bloomberg.com/markets/news.rss",
        "https://www.ft.com/rss/home",
        "https://www.wsj.com/xml/rss/3_7085.xml",
        "https://rss.dw.com/rdf/rss-en-bus",
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://feeds.bbci.co.uk/news/business/rss.xml",
    ],
    "commodities": [
        "https://www.agrimoney.com/rss.xml",
        "https://oilprice.com/rss/main",
        "https://www.mining.com/feed/",
        "https://www.metalbulletin.com/rss",
        "https://www.worldgrain.com/rss",
        "https://www.agriculture.com/rss/news_rss.xml",
        "https://www.icis.com/explore/resources/news/rss/",
        "https://www.steelorbis.com/steel-news/rss.xml",
    ],
    "manufacturing": [
        "https://www.industryweek.com/rss",
        "https://www.manufacturingglobal.com/rss.xml",
        "https://www.supplychainbrain.com/rss/latest",
        "https://www.logisticsmgmt.com/rss",
        "https://www.industrytoday.com/feed/",
        "https://semiconductordigest.com/feed/",
        "https://www.just-auto.com/rss",
    ],
    "climate": [
        "https://reliefweb.int/disasters/rss.xml",
        "https://www.preventionweb.net/news/rss.xml",
        "https://www.who.int/rss-feeds/news-english.xml",
        "https://www.gdacs.org/xml/rss.xml",
    ],
}

ENTITY_FEED_MAP = {
    "supplier":  ["manufacturing", "geopolitics", "logistics"],
    "material":  ["commodities",   "geopolitics", "climate"],
    "logistics": ["logistics",     "geopolitics"],
    "facility":  ["manufacturing", "climate",     "logistics"],
    "baseline":  ["logistics", "geopolitics", "commodities", "manufacturing", "climate"],
}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — KNOWN ENTITY ALIASES
#
# Many companies and locations have common alternative names used in the press.
# Adding these ensures articles that say "Taiwan Semiconductor" instead of
# "TSMC" are still matched to the right entity.
# ══════════════════════════════════════════════════════════════════════════════

ENTITY_ALIASES = {
    # ── Suppliers ────────────────────────────────────────────────────────────
    # IMPORTANT: supplier aliases use company name + country ONLY.
    # Do NOT include generic material words (e.g. "chip", "semiconductor",
    # "foundry") here — those are too broad and match unrelated articles.
    # An article about a Canadian startup winning a "semiconductor award" would
    # match TSMC via "semiconductor"; requiring "tsmc" or "taiwan" prevents this.
    "tsmc":                  ["tsmc", "taiwan semiconductor manufacturing",
                              "taiwan semiconductor", "taiwan chip", "hsinchu fab",
                              "taiwan foundry"],
    "foxconn":               ["foxconn", "hon hai", "foxconn technology",
                              "foxconn industrial", "zhengzhou foxconn"],
    "samsung semiconductor": ["samsung semiconductor", "samsung foundry",
                              "samsung electronics memory", "samsung hbm",
                              "hwaseong fab", "pyeongtaek fab"],

    # ── Materials (keep broad — these are commodity articles, not company ones) ─
    "rare earth metals":     ["rare earth", "rare-earth", "neodymium", "dysprosium",
                              "cobalt", "lithium", "gallium", "germanium",
                              "critical mineral", "critical minerals"],
    "silicon wafers":        ["silicon wafer", "polysilicon", "siltronic",
                              "shin-etsu", "sumco", "wafer supply"],

    # ── Ports / logistics ────────────────────────────────────────────────────
    "shanghai port":         ["shanghai port", "port of shanghai", "yangshan",
                              "waigaoqiao", "shanghai container"],
    "busan port":            ["busan port", "port of busan", "pusan port",
                              "busan terminal"],

    # ── Countries / regions ──────────────────────────────────────────────────
    "taiwan":                ["taiwan", "taipei", "strait of taiwan",
                              "taiwan strait", "cross-strait"],
    "china":                 ["china", "chinese", "prc", "beijing", "shenzhen",
                              "guangdong", "guangzhou"],
    "south korea":           ["south korea", "south korean", "seoul", "korea semiconductor"],
    "japan":                 ["japan", "japanese", "tokyo", "osaka", "japan supply"],
    "india":                 ["india", "indian", "bangalore", "bengaluru", "india manufacturing"],
    "germany":               ["germany", "german", "munich", "deutschland", "germany logistics"],

    # ── Logistics routes ─────────────────────────────────────────────────────
    "maersk":                ["maersk", "a.p. moller", "ap moller"],
    "hapag-lloyd":           ["hapag-lloyd", "hapag lloyd", "hapag"],
    "asia-europe":           ["asia-europe", "asia europe", "suez canal", "red sea",
                              "indian ocean route", "malacca strait",
                              "strait of malacca", "europe asia shipping"],
    "asia-us":               ["asia-us", "asia us", "transpacific", "trans-pacific",
                              "long beach port", "los angeles port", "seattle port",
                              "pacific shipping"],
}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — DISRUPTION SIGNAL TAXONOMY
# ══════════════════════════════════════════════════════════════════════════════

CRITICAL_SIGNALS = [
    "halt", "shut down", "shutdown", "suspended", "closure", "closed",
    "blockade", "force majeure", "emergency", "grounded", "seized",
    "sanctions", "export ban", "import ban", "embargo", "war", "invasion",
    "military action", "coup", "nationalised", "nationalized",
    "strike", "work stoppage", "lockout",
    "explosion", "fire", "dam break", "chemical spill",
    "bankruptcy", "insolvency", "liquidation", "defaulted",
    "pandemic", "quarantine lockdown",
]

HIGH_SIGNALS = [
    "disruption", "congestion", "port closure", "canal closure", "vessel delay",
    "rerouted", "diverted", "piracy", "hijacked", "grounding", "aground",
    "flood", "earthquake", "typhoon", "cyclone", "hurricane", "tornado",
    "wildfire", "drought", "freeze", "heatwave", "tsunami", "landslide",
    "tariff", "trade war", "trade dispute", "anti-dumping", "quota",
    "export restriction", "import restriction",
    "shortage", "delay", "backlog", "stockout", "rationing", "allocation",
    "price surge", "price spike", "soaring", "surging", "price crisis",
    "recall", "product ban", "safety halt", "compliance failure",
    "protest", "unrest", "labour shortage", "worker shortage",
    "cyber attack", "ransomware", "system outage", "data breach",
    "power outage", "blackout", "grid failure", "fuel shortage",
    "outbreak", "epidemic", "quarantine", "border closure",
]

MEDIUM_SIGNALS = [
    "risk", "concern", "warning", "tension", "alert", "monitor",
    "slowdown", "pressure", "decline", "volatility", "uncertainty",
    "investigation", "fine", "penalty", "review", "scrutiny",
    "inflation", "cost increase", "energy crisis",
    "capacity crunch", "equipment shortage", "driver shortage",
    "crop failure", "water shortage", "heat stress",
]

DISRUPTION_SIGNALS_ANY = list(dict.fromkeys(
    CRITICAL_SIGNALS + HIGH_SIGNALS + MEDIUM_SIGNALS + [
        "supply chain", "disruption", "shortage", "delay", "conflict",
        "diverted", "divert", "reroute", "rerouted", "cancelled", "reversed",
        "crises", "crisis", "affected", "impacted", "halted",
    ]
))

SUPPLY_CHAIN_KEYWORDS = [
    "supply chain", "port", "shipping", "freight", "logistics", "cargo",
    "vessel", "manufacturing", "factory", "plant", "warehouse",
    "semiconductor", "lithium", "rare earth", "commodity",
    "trade", "import", "export", "tariff", "sanctions",
    "shortage", "disruption", "delay", "mining", "refinery",
    "assembly", "production", "container", "maritime", "tanker",
    "carrier", "rail", "trucking", "customs",
    "fertilizer", "fertiliser", "wheat", "grain", "soybeans",
    "diesel", "fuel oil", "cobalt", "nickel", "copper",
    "aluminium", "aluminum", "steel", "polysilicon", "palladium",
    "phosphate", "potash", "lng", "crude oil", "natural gas",
    "semiconductor fab", "foundry", "wafer", "chip", "battery",
    "ev battery", "active ingredient", "pharma",
]

POSITIVE_ONLY_SIGNALS = [
    # Growth / records
    "record growth", "record revenue", "record export", "record production",
    "record shipment", "best quarter",
    # Awards / recognition (catches "Emtar wins Semiconductor Award")
    "receives award", "wins award", "awarded the", "achievement award",
    "startup of the year", "company of the year", "award for",
    # Grants / government investment (catches "DOE awards $67M")
    "awarded grant", "awarded funding", "awards grant", "awards funding",
    "letter of intent", "signs loi", "proposed award", "chips award",
    # Partnerships / agreements (positive business news, not disruptions)
    "new contract", "agreement signed", "signs agreement", "signs distribution",
    "distribution agreement", "partnership agreement", "collaboration agreement",
    "multi-year agreement", "deepens collaboration", "deepen collaboration",
    # Expansion / investment
    "expansion", "inaugurates", "milestone", "new facility", "opens new",
    "celebrates", "investment in", "optimise operations", "enhance production",
    "capacity increase", "launches new", "boosts output", "groundbreaking",
    "ribbon cutting", "new plant", "new hub",
    # Policy welcomes / industry statements (catches "ESIA welcomes EU Chips Act")
    "welcomed the", "welcomes the", "pleased to announce", "proud to announce",
    "today announced", "today welcomed", "important next step",
    "tech sovereignty", "industrial reality", "ambition into",
    # Positive outlook
    "ready to adapt", "demonstrates ability", "optimistic", "poised for growth",
]


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — FILTER FUNCTIONS  (v7 adds Gate C)
# ══════════════════════════════════════════════════════════════════════════════

def _contains_signal(text: str, signal: str) -> bool:
    """
    Check if a disruption signal appears in text as a meaningful match.

    Short signals (≤5 chars) like 'war', 'fire', 'fine', 'coup' are checked
    with word boundaries to prevent false substring matches:
      - 'war' should NOT match inside 'award', 'forward', 'hardware'
      - 'fire' should NOT match inside 'Firefox', 'firewall', 'supplier'
      - 'fine' should NOT match inside 'refinery', 'defined'

    Longer signals (>5 chars) use simple substring — they're specific enough
    that false positives are rare.
    """
    if len(signal) <= 5:
        return bool(re.search(r'\b' + re.escape(signal) + r'\b', text))
    return signal in text


def classify_impact(text: str, entity_kws: set = None) -> str:
    """
    Returns highest severity level. Uses word-boundary matching for short
    signals to prevent 'war' inside 'award', 'fire' inside 'supplier', etc.

    v8: if entity_kws provided, CRITICAL/HIGH require the disruption signal
    to appear within 120 chars of an entity keyword (proximity check).
    """
    t = text.lower()

    if entity_kws:
        def near_entity(signal: str) -> bool:
            # Find all occurrences of the signal
            if len(signal) <= 5:
                matches = [m.start() for m in re.finditer(r'\b' + re.escape(signal) + r'\b', t)]
            else:
                idx = t.find(signal)
                matches = [idx] if idx != -1 else []
            for idx in matches:
                window = t[max(0, idx - 120): idx + 120 + len(signal)]
                if any(kw in window for kw in entity_kws):
                    return True
            return False

        if any(near_entity(s) for s in CRITICAL_SIGNALS): return "CRITICAL"
        if any(near_entity(s) for s in HIGH_SIGNALS):     return "HIGH"
        if any(_contains_signal(t, s) for s in MEDIUM_SIGNALS): return "MEDIUM"
        return "LOW"
    else:
        if any(_contains_signal(t, s) for s in CRITICAL_SIGNALS): return "CRITICAL"
        if any(_contains_signal(t, s) for s in HIGH_SIGNALS):     return "HIGH"
        if any(_contains_signal(t, s) for s in MEDIUM_SIGNALS):   return "MEDIUM"
        return "LOW"


def has_disruption_signal(text: str) -> bool:
    t = text.lower()
    return any(_contains_signal(t, s) for s in DISRUPTION_SIGNALS_ANY)


def is_positive_only(article: dict) -> bool:
    """
    Returns True if this is a purely positive/neutral story with no real
    disruption signal — i.e. it should be excluded from risk intelligence.

    Logic: positive phrase present AND no genuine disruption signal.
    Uses word-boundary-safe disruption check.
    """
    text = (article.get("title", "") + " " + article.get("description", "")).lower()
    has_positive = any(s in text for s in POSITIVE_ONLY_SIGNALS)
    has_disruption = has_disruption_signal(text)
    return has_positive and not has_disruption


def article_matches_entity(article: dict, entity_keywords: set) -> bool:
    """
    Gate C — ENTITY MATCH GATE (NEW in v7)

    The article text must contain at least one token or phrase from THIS
    SPECIFIC entity's keyword set.

    This is the critical gate that was missing in v6. Without it, a
    Bangladesh fruit story passes because it mentions "airfreight" (a
    generic supply chain word) — even though NovaTech has no Bangladesh
    supplier, port, or material.

    With Gate C, that article fails because none of the entity's keywords
    (tsmc, taiwan, foxconn, samsung, shanghai, etc.) appear in it.
    """
    text = (article.get("title", "") + " " + article.get("description", "")).lower()

    # Check single tokens
    single_kw = {kw for kw in entity_keywords if " " not in kw}
    phrase_kw = {kw for kw in entity_keywords if " " in kw}

    # At least one entity keyword must appear in the article
    if any(kw in text for kw in single_kw):
        return True
    if any(ph in text for ph in phrase_kw):
        return True

    return False


def is_relevant_for_entity(article: dict, entity_kws: set) -> bool:
    """
    Combined 3-gate check for entity-specific articles:
      Gate A: Supply chain topic keyword present
      Gate B: Disruption signal present
      Gate C: Entity-specific keyword present (NEW — the critical fix)
    """
    text = (article.get("title", "") + " " + article.get("description", "")).lower()

    gate_a = any(kw in text for kw in SUPPLY_CHAIN_KEYWORDS)
    gate_b = has_disruption_signal(text)
    gate_c = article_matches_entity(article, entity_kws)

    return gate_a and gate_b and gate_c


def is_relevant_for_baseline(article: dict) -> bool:
    """
    Baseline articles (global risk) get a STRICTER check:
      - Must be supply chain topic (Gate A)
      - Must have disruption signal (Gate B)
      - Must have AT LEAST 2 disruption signals (raised bar for unattributed articles)
    This prevents generic single-mention articles from inflating the baseline.
    """
    text = (article.get("title", "") + " " + article.get("description", "")).lower()

    if not any(kw in text for kw in SUPPLY_CHAIN_KEYWORDS):
        return False

    # Count how many distinct disruption signals appear
    signal_count = sum(1 for s in DISRUPTION_SIGNALS_ANY if s in text)
    return signal_count >= 2


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — ENTITY KEYWORD BUILDER  (v7 adds alias expansion)
# ══════════════════════════════════════════════════════════════════════════════

_STOPWORDS = {
    "a","an","the","of","in","on","at","to","for","and","or","but",
    "is","are","was","were","be","been","by","from","with","as",
    "its","it","this","that","these","those","we","our","my","your",
    "no","not","also","than","more","very","just","only","both",
    # Additional generic words that should NOT be entity keywords:
    "global", "international", "new", "latest", "update", "report",
    "company", "group", "corp", "inc", "ltd", "co",
}


def _tokenise(text: str) -> list:
    words = re.sub(r"[^a-z0-9\s]", " ", text.lower()).split()
    return [w for w in words if len(w) >= 3 and w not in _STOPWORDS]


def _clean(val) -> str:
    return val.strip() if isinstance(val, str) else ""


def _expand_with_aliases(tokens: set, phrases: list) -> set:
    """
    For each token/phrase in the entity's keyword set, check ENTITY_ALIASES.
    If a match is found, add ALL known aliases for that entity.

    Example: tokens contains "tsmc"
    → adds ["taiwan semiconductor", "tsmc", "taiwan chip", "hsinchu"]

    Example: tokens contains "rare"  (from "Rare Earth Metals")
    → "rare" alone won't match, but phrase "rare earth metals" in phrases
       → adds ["rare earth", "rare-earth", "neodymium", ...]
    """
    expanded = set(tokens)

    # Check against alias keys using full phrase matches first
    all_text = " ".join(phrases).lower()
    for alias_key, alias_list in ENTITY_ALIASES.items():
        if alias_key in all_text:
            expanded.update(alias_list)

    # Also check individual tokens against alias keys
    for token in tokens:
        for alias_key, alias_list in ENTITY_ALIASES.items():
            if token in alias_key or alias_key in token:
                expanded.update(alias_list)

    return expanded


def entity_keywords(entity_type: str, fields: dict) -> set | None:
    tokens = set()
    raw_phrases = []

    if entity_type == "supplier":
        name     = _clean(fields.get("name",     ""))
        material = _clean(fields.get("material", ""))
        location = _clean(fields.get("location", ""))
        raw_phrases = [name, material, location]

    elif entity_type == "material":
        commodity = _clean(fields.get("commodity", ""))
        region    = _clean(fields.get("region",    ""))
        if not commodity or len(_tokenise(commodity)) == 0:
            return None
        raw_phrases = [commodity, region]

    elif entity_type == "logistics":
        port    = _clean(fields.get("port",    ""))
        carrier = _clean(fields.get("carrier", ""))
        route   = _clean(fields.get("route",   ""))
        raw_phrases = [port, carrier, route]

    elif entity_type == "facility":
        name     = _clean(fields.get("name",     ""))
        location = _clean(fields.get("location", ""))
        raw_phrases = [name, location]

    else:
        return None

    for phrase in raw_phrases:
        tokens.update(_tokenise(phrase))

    for phrase in raw_phrases:
        cleaned = phrase.lower().strip()
        if cleaned and " " in cleaned:
            tokens.add(cleaned)

    if not tokens:
        return None

    # v8: expand with known aliases for richer matching
    # For suppliers, only expand using company name + location tokens,
    # NOT the material field — avoids "semiconductor" → generic chip words
    if entity_type == "supplier":
        name_loc_phrases = [raw_phrases[0], raw_phrases[2]]  # name, location only
        tokens = _expand_with_aliases(tokens, name_loc_phrases)
    else:
        tokens = _expand_with_aliases(tokens, raw_phrases)

    return tokens


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — RSS FETCHER
# ══════════════════════════════════════════════════════════════════════════════

def _article_id(title: str, url: str = "") -> str:
    cleaned = re.sub(r"[^a-z0-9]", "", (title + url).lower())
    return hashlib.md5(cleaned.encode()).hexdigest()


def _parse_published(entry) -> datetime | None:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime(*entry.published_parsed[:6])
        except Exception:
            pass
    return None


def fetch_rss_for_entity(keywords: set, entity_type: str,
                         max_results: int = MAX_PER_ENTITY) -> list:
    """
    Scans RSS feeds for the entity type and scores by keyword overlap.
    Returns raw candidates — entity-match filtering happens in the caller.
    """
    cutoff      = datetime.utcnow() - timedelta(days=DAYS_BACK)
    feed_groups = ENTITY_FEED_MAP.get(entity_type, ENTITY_FEED_MAP["baseline"])
    candidates  = []

    single_kw = {kw for kw in keywords if " " not in kw}
    phrase_kw = {kw for kw in keywords if " " in kw}

    for group in feed_groups:
        for feed_url in RSS_FEEDS.get(group, []):
            try:
                feed        = feedparser.parse(feed_url)
                source_name = feed.feed.get("title", feed_url.split("/")[2])

                for entry in feed.entries:
                    title   = entry.get("title",   "") or ""
                    summary = (entry.get("summary", "")
                               or entry.get("description", "") or "")
                    text    = (title + " " + summary).lower()

                    score  = sum(1 for kw in single_kw if kw in text)
                    score += sum(2 for ph in phrase_kw if ph in text)

                    if score < MIN_HITS:
                        continue

                    pub_dt = _parse_published(entry) or datetime.utcnow()
                    if pub_dt < cutoff:
                        continue

                    candidates.append({
                        "title":        title,
                        "description":  summary[:350],
                        "source":       source_name,
                        "publishedAt":  pub_dt.isoformat(),
                        "url":          entry.get("link", "#"),
                        "urlToImage":   "",
                        "impact_level": classify_impact(title + " " + summary, keywords),
                        "_api":         "RSS",
                        "_score":       score,
                        "_feed_group":  group,
                    })

            except Exception as exc:
                print(f"[RSS] Failed to parse {feed_url}: {exc}")
                continue

    candidates.sort(key=lambda a: -a["_score"])
    result = candidates[:max_results]
    print(f"[RSS:{entity_type}] keywords={sorted(list(keywords))[:6]} "
          f"→ {len(result)} articles (from {len(candidates)} candidates)")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — _best_category
# ══════════════════════════════════════════════════════════════════════════════

def _best_category(article: dict, fetched_under: str,
                   entity_label_keywords: dict) -> str:
    text = (article.get("title", "") + " " + article.get("description", "")).lower()

    def score(kws: set) -> int:
        s  = sum(1 for kw in kws if " " not in kw and kw in text)
        s += sum(2 for kw in kws if " " in kw     and kw in text)
        return s

    best_label = fetched_under
    best_score = score(entity_label_keywords.get(fetched_under, set()))

    for label, kws in entity_label_keywords.items():
        if label == fetched_under:
            continue
        s = score(kws)
        if s > best_score + 1:
            best_score = s
            best_label = label

    return best_label


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — RISK SCORER
# ══════════════════════════════════════════════════════════════════════════════

def compute_risk(articles: list) -> dict:
    levels = [a.get("impact_level", "LOW") for a in articles]
    score  = (levels.count("CRITICAL") * 10 +
              levels.count("HIGH")     *  5 +
              levels.count("MEDIUM")   *  2 +
              levels.count("LOW")      *  1)

    if score >= 15:
        return dict(level="CRITICAL", color="#DC2626", bg="#FEF2F2",
                    message="⚠️ Immediate action required — Severe disruptions detected across multiple nodes")
    if score >= 8:
        return dict(level="HIGH",     color="#EA580C", bg="#FFF7ED",
                    message="🔴 Elevated risk — Active monitoring and contingency planning strongly recommended")
    if score >= 4:
        return dict(level="MEDIUM",   color="#D97706", bg="#FFFBEB",
                    message="🟡 Moderate disruptions possible — Watch key suppliers and logistics partners")
    return     dict(level="LOW",      color="#059669", bg="#ECFDF5",
                    message="🟢 Stable conditions — Continue routine supply chain monitoring")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10 — JSON PERSISTENCE
# ══════════════════════════════════════════════════════════════════════════════

def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"\s+", "_", text)


def save_to_json(client_name, profile, articles, risk, breakdown, stats):
    """
    v8: Always overwrites the daily JSON with the latest run's articles.
    No more appending stale articles from previous runs in the same day.
    The 'runs' list still accumulates run history for audit purposes,
    but 'articles' always reflects only the current run's results.
    """
    slug     = slugify(client_name) or "unknown_client"
    today    = datetime.utcnow().strftime("%Y-%m-%d")
    out_dir  = DATA_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{today}.json"

    # Load existing run history if file exists (keep run log, replace articles)
    existing_runs = []
    if out_path.exists():
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            existing_runs = existing.get("runs", [])
        except Exception:
            existing_runs = []

    existing_runs.append({
        "timestamp":      datetime.utcnow().isoformat(),
        "overall_risk":   risk["level"],
        "articles_added": len(articles),
        "breakdown":      breakdown,
    })

    payload = {
        "client_name": client_name,
        "client_slug": slug,
        "profile":     profile,
        "created_at":  datetime.utcnow().isoformat(),
        "runs":        existing_runs,
        "stats":       stats,
        "articles":    articles,   # always the latest run only — no stale accumulation
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[JSON] Overwritten → {out_path}  ({len(articles)} articles, "
          f"{len(existing_runs)} total runs today)")
    return str(out_path)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 11 — FLASK ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    """
    v7 analysis flow — key change is entity-specific filtering.

    For each entity:
      1. entity_keywords()               — build keyword set + expand aliases
      2. fetch_rss_for_entity()          — scan targeted feeds, score articles
      3. is_relevant_for_entity()        — Gates A + B + C (entity match)
         OR is_relevant_for_baseline()   — stricter 2-signal rule for global
      4. is_positive_only()              — exclude milestone/expansion articles
      5. Deduplicate across entities
      6. _best_category()                — re-attribute to best entity label

    Gate C explanation:
      For an article to count under "Supplier: TSMC", it must contain one of:
        tsmc, taiwan semiconductor, taiwan chip, hsinchu, semiconductor, chip,
        taiwan, taipei, etc.
      "Bangladesh airfreight rates" contains none of these → rejected.
      "Taiwan Strait tensions disrupt chip shipments" contains "taiwan",
      "chip" → passes → correctly flagged under TSMC.
    """
    try:
        data        = request.json
        client_name = data.get("client_name", "Unknown Client").strip()
        tier1       = data.get("tier1_suppliers", [])
        raw_mats    = data.get("raw_materials",   [])
        log_nodes   = data.get("logistics_nodes", [])
        own_facs    = data.get("own_facilities",  [])

        entity_list = []
        skipped     = []

        def _add(label, etype, fields):
            kws = entity_keywords(etype, fields)
            if kws:
                entity_list.append((label, kws, etype))
            else:
                skipped.append(label)
                print(f"[Skip] {label} — insufficient signal")

        for i, s in enumerate(tier1):
            _add(f"Supplier: {_clean(s.get('name','')) or _clean(s.get('material','')) or f'#{i+1}'}",
                 "supplier", s)

        for i, m in enumerate(raw_mats):
            _add(f"Material: {_clean(m.get('commodity','')) or f'#{i+1}'}",
                 "material", m)

        for i, n in enumerate(log_nodes):
            _add(f"Logistics: {_clean(n.get('port','')) or _clean(n.get('carrier','')) or _clean(n.get('route','')) or f'#{i+1}'}",
                 "logistics", n)

        for i, f in enumerate(own_facs):
            _add(f"Facility: {_clean(f.get('name','')) or _clean(f.get('location','')) or f'#{i+1}'}",
                 "facility", f)

        # Global baseline — stricter filter applied separately
        baseline_kws = {
            "supply chain", "disruption", "shortage", "logistics",
            "freight", "port", "shipping", "sanctions", "tariff",
            "semiconductor", "rare earth", "taiwan", "china", "korea",
            "shanghai", "busan", "india", "germany",
        }
        entity_list.append(("Global Baseline", baseline_kws, "baseline"))

        print(f"\n[Analyze] {client_name} — "
              f"{len(entity_list)} entities active, {len(skipped)} skipped")

        seen_ids         = set()
        all_articles     = []
        breakdown        = {}
        entity_label_kws = {label: kws for label, kws, _ in entity_list}

        for label, kws, etype in entity_list:
            raw = fetch_rss_for_entity(kws, etype)

            # ── v7 ENTITY-SPECIFIC FILTER ─────────────────────────────────
            if etype == "baseline":
                filtered = [a for a in raw
                            if is_relevant_for_baseline(a)
                            and not is_positive_only(a)]
            else:
                filtered = [a for a in raw
                            if is_relevant_for_entity(a, kws)
                            and not is_positive_only(a)]

            rejected = len(raw) - len(filtered)
            if rejected:
                print(f"  [{label}] Rejected {rejected} articles that didn't "
                      f"mention entity-specific keywords")

            new_for_label = []
            for a in filtered:
                aid = _article_id(a["title"], a.get("url", ""))
                if aid not in seen_ids:
                    seen_ids.add(aid)
                    a["category"] = _best_category(a, label, entity_label_kws)
                    all_articles.append(a)
                    new_for_label.append(a)

            breakdown[label] = len(new_for_label)
            status_note = (f"✓ {len(new_for_label)} articles"
                           if new_for_label else "— no disruption signals")
            print(f"  {label}: {status_note}")

        # Sort and trim
        impact_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        all_articles.sort(key=lambda a: (
            impact_order.get(a.get("impact_level", "LOW"), 9),
            -(int(datetime.fromisoformat(
                a["publishedAt"].replace("Z", "+00:00")
            ).timestamp()) if a.get("publishedAt") else 0)
        ))

        final  = all_articles[:MAX_FINAL]
        risk   = compute_risk(final)
        levels = [a.get("impact_level") for a in final]

        stats = {
            "total_articles":        len(final),
            "critical_alerts":       levels.count("CRITICAL"),
            "high_alerts":           levels.count("HIGH"),
            "medium_alerts":         levels.count("MEDIUM"),
            "low_alerts":            levels.count("LOW"),
            "suppliers_count":       len(tier1),
            "materials_count":       len(raw_mats),
            "logistics_nodes_count": len(log_nodes),
            "facilities_count":      len(own_facs),
            "entities_scanned":      len(entity_list),
            "entities_skipped":      len(skipped),
        }

        profile    = dict(tier1_suppliers=tier1, raw_materials=raw_mats,
                          logistics_nodes=log_nodes, own_facilities=own_facs)
        saved_path = save_to_json(client_name, profile, final, risk, breakdown, stats)

        return __import__("flask").jsonify({
            "status":             "success",
            "client_name":        client_name,
            "overall_risk":       risk["level"],
            "risk_color":         risk["color"],
            "risk_bg_light":      risk["bg"],
            "risk_message":       risk["message"],
            "news":               final,
            "query_breakdown":    breakdown,
            "saved_to":           saved_path,
            "analysis_timestamp": datetime.now().strftime("%B %d, %Y at %I:%M %p"),
            "stats":              stats,
            "skipped_entities":   skipped,
        })

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return __import__("flask").jsonify({"status": "error", "message": str(exc)}), 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
"""
utils/query_generator.py
========================
Three-prong query generation engine for the Supply Chain Disruption
Intelligence System.

Prong 1 — Entity prong    : Supplier / logistics node name verbatim
Prong 2 — Geo prong       : "City" AND (all disruption terms)
Prong 3 — Commodity prong : "Commodity" AND (commodity disruption terms)
                            + "Origin region" AND commodity AND (origin terms)

The module also builds a rich exposure_map used by downstream modules
(rss_fetcher, relevance_scorer) to do country-level source dispatch
and per-article node linkage.
"""

import json
import os
import re

# ==========================================
# CONFIG PATHS
# ==========================================

_BASE = os.path.join(
    os.path.dirname(__file__),
    "..",
    "config"
)

def _load(filename):
    path = os.path.join(_BASE, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ==========================================
# LAZY-LOADED CONFIG SINGLETONS
# ==========================================

_countries_cfg      = None
_materials_cfg      = None
_ports_cfg          = None
_routes_cfg         = None
_disruption_cfg     = None


def _countries():
    global _countries_cfg
    if _countries_cfg is None:
        _countries_cfg = _load("countries.json")
    return _countries_cfg


def _materials():
    global _materials_cfg
    if _materials_cfg is None:
        _materials_cfg = _load("materials.json")
    return _materials_cfg


def _ports():
    global _ports_cfg
    if _ports_cfg is None:
        _ports_cfg = _load("ports.json")
    return _ports_cfg


def _routes():
    global _routes_cfg
    if _routes_cfg is None:
        _routes_cfg = _load("logistics_routes.json")
    return _routes_cfg


def _disruption():
    global _disruption_cfg
    if _disruption_cfg is None:
        _disruption_cfg = _load("disruption_terms.json")
    return _disruption_cfg


# ==========================================
# HELPERS
# ==========================================

def _all_disruption_terms():
    """
    Flatten every term from every domain into one deduplicated list.
    """
    seen  = set()
    terms = []
    for domain_data in _disruption()["domains"].values():
        for t in domain_data["terms"]:
            if t not in seen:
                seen.add(t)
                terms.append(t)
    return terms


def _domain_terms(domain_name):
    """
    Return terms for a single domain (e.g. 'labour').
    """
    return _disruption()["domains"].get(domain_name, {}).get("terms", [])


def _resolve_country(raw_name):
    """
    Case-insensitive lookup of a country name in countries.json.
    Returns the canonical name or None if not found.
    """
    countries = _countries()["countries"]
    for canonical, _ in countries.items():
        if canonical.lower() == raw_name.lower():
            return canonical
    return None


def _resolve_port(raw_name):
    """
    Match a port by its key or aliases list in ports.json.
    Returns (canonical_port_name, port_record) or (None, None).
    """
    ports = _ports()["ports"]
    raw_lower = raw_name.lower()
    for port_key, port_data in ports.items():
        if port_key.lower() == raw_lower:
            return port_key, port_data
        for alias in port_data.get("aliases", []):
            if alias.lower() == raw_lower:
                return port_key, port_data
    return None, None


def _resolve_route(raw_name):
    """
    Match a trade route / chokepoint by key.
    Returns the route record or None.
    """
    routes = _routes()
    raw_lower = raw_name.lower()
    for section in ("strategic_chokepoints", "major_trade_corridors"):
        for route_key, route_data in routes.get(section, {}).items():
            if route_key.lower() == raw_lower:
                return route_key, route_data
    return None, None


def _geo_prong(city, country, all_terms, split_threshold=400):
    """
    Build one or more geo-prong query strings for a city.

    If the full query would exceed split_threshold chars, emit one
    sub-query per disruption domain instead.  Coverage is identical.
    """
    terms_str = " OR ".join(f'"{t}"' for t in all_terms)
    full = f'"{city}" AND ({terms_str})'

    if len(full) <= split_threshold:
        return [full]

    # Split by domain
    queries = []
    for domain_name in _disruption()["domains"]:
        d_terms = _domain_terms(domain_name)
        d_str   = " OR ".join(f'"{t}"' for t in d_terms)
        queries.append(f'"{city}" AND ({d_str})')
    return queries


def _commodity_prongs(commodity_key, material_record):
    """
    Build commodity prong queries for one material:
      - "{commodity}" AND (commodity disruption terms)
      - "{origin_region}" AND {commodity} AND (origin terms)
    """
    disruption = _disruption()
    comm_terms   = disruption.get("commodity_disruption_terms", [])
    origin_terms = disruption.get("commodity_origin_terms", [])

    queries  = []
    synonyms = material_record.get("synonyms", [])

    # Primary commodity term (prefer first synonym as it's usually the
    # most recognisable trade name, e.g. "lithium carbonate")
    primary = synonyms[0] if synonyms else commodity_key

    # Prong A: commodity AND disruption
    comm_str = " OR ".join(f'"{t}"' for t in comm_terms)
    queries.append(f'"{primary}" AND ({comm_str})')

    # Prong B: origin region AND commodity AND origin events
    origin_str = " OR ".join(f'"{t}"' for t in origin_terms)
    for region in material_record.get("top_producers", [])[:3]:
        queries.append(
            f'"{region}" AND "{primary}" AND ({origin_str})'
        )

    return queries


# ==========================================
# EXPOSURE MAP BUILDER
# ==========================================

def build_exposure_map(profile):
    """
    Convert a client profile dict into a structured exposure_map.

    exposure_map keys
    -----------------
    countries   : list[str]   — canonical country names
    cities      : dict        — {country: [city, ...]}
    materials   : list[str]   — raw material keys
    ports       : list[str]   — canonical port keys
    routes      : list[str]   — route / chokepoint keys
    suppliers   : list[str]   — tier-1 supplier names (entity prong)
    logistics_nodes : list[str]  — logistics node names (entity prong)
    material_records : dict   — {material_key: record from materials.json}
    port_records     : dict   — {port_key: record from ports.json}
    route_records    : dict   — {route_key: record}
    """

    countries_cfg  = _countries()["countries"]
    materials_cfg  = _materials()["materials"]
    ports_cfg      = _ports()["ports"]

    exposure = {
        "countries":       [],
        "cities":          {},
        "materials":       [],
        "ports":           [],
        "routes":          [],
        "suppliers":       [],
        "logistics_nodes": [],
        "material_records":  {},
        "port_records":      {},
        "route_records":     {},
    }

    seen_countries = set()
    seen_materials = set()
    seen_ports     = set()
    seen_routes    = set()

    # --------------------------------------------------
    # 1. Tier-1 Suppliers → countries + cities + entity
    # --------------------------------------------------
    for supplier in profile.get("tier1_suppliers", []):
        name    = supplier.get("name", "").strip()
        country = supplier.get("country", "").strip()
        city    = supplier.get("city", "").strip()

        if name:
            exposure["suppliers"].append(name)

        canonical = _resolve_country(country)
        if canonical and canonical not in seen_countries:
            seen_countries.add(canonical)
            exposure["countries"].append(canonical)
            exposure["cities"][canonical] = (
                countries_cfg.get(canonical, {}).get("major_cities", [])
            )

        # If client supplied a specific city, prepend it so it's
        # searched first
        if city and canonical:
            city_list = exposure["cities"].setdefault(canonical, [])
            if city not in city_list:
                city_list.insert(0, city)

    # --------------------------------------------------
    # 2. Raw Materials → material records + origin countries
    # --------------------------------------------------
    for mat in profile.get("raw_materials", []):
        commodity = mat.get("commodity", "").strip().lower()
        region    = mat.get("region", "").strip()

        # Match to materials.json
        matched_key = None
        for key, rec in materials_cfg.items():
            all_names = [key] + [s.lower() for s in rec.get("synonyms", [])]
            if commodity in all_names:
                matched_key = key
                break

        if matched_key and matched_key not in seen_materials:
            seen_materials.add(matched_key)
            exposure["materials"].append(matched_key)
            exposure["material_records"][matched_key] = materials_cfg[matched_key]

            # Pull in top producer countries for geo coverage
            for producer in materials_cfg[matched_key].get("top_producers", [])[:3]:
                canonical = _resolve_country(producer)
                if canonical and canonical not in seen_countries:
                    seen_countries.add(canonical)
                    exposure["countries"].append(canonical)
                    exposure["cities"][canonical] = (
                        countries_cfg.get(canonical, {}).get("major_cities", [])
                    )

        elif matched_key is None and commodity:
            # Unknown material — still track the name for entity prong
            exposure["materials"].append(commodity)

    # --------------------------------------------------
    # 3. Logistics Nodes → ports / routes / countries
    # --------------------------------------------------
    for node in profile.get("logistics_nodes", []):
        node_name = node.get("name", "").strip() if isinstance(node, dict) else str(node).strip()
        node_type = node.get("type", "").strip().lower() if isinstance(node, dict) else ""

        if not node_name:
            continue

        exposure["logistics_nodes"].append(node_name)

        # Try port match
        port_key, port_rec = _resolve_port(node_name)
        if port_key and port_key not in seen_ports:
            seen_ports.add(port_key)
            exposure["ports"].append(port_key)
            exposure["port_records"][port_key] = port_rec

            # Add port country
            country = port_rec.get("country", "")
            canonical = _resolve_country(country)
            if canonical and canonical not in seen_countries:
                seen_countries.add(canonical)
                exposure["countries"].append(canonical)
                exposure["cities"][canonical] = (
                    countries_cfg.get(canonical, {}).get("major_cities", [])
                )
            continue

        # Try route / chokepoint match
        route_key, route_rec = _resolve_route(node_name)
        if route_key and route_key not in seen_routes:
            seen_routes.add(route_key)
            exposure["routes"].append(route_key)
            exposure["route_records"][route_key] = route_rec

    return exposure


# ==========================================
# QUERY GENERATOR
# ==========================================

def generate_queries(exposure):
    """
    Generate the full three-prong query list from an exposure_map.

    Returns a list of query strings, deduplicated and ordered:
      1. Entity prongs (supplier/logistics node names)
      2. Geo prongs (city + all disruption terms, split by domain if long)
      3. Commodity prongs (material + disruption / origin + material + events)

    Each query is a string ready to pass directly to NewsAPI or a
    Google News RSS search URL.
    """

    queries = []
    seen    = set()
    all_terms = _all_disruption_terms()

    def _add(q):
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            queries.append(q)

    # --------------------------------------------------
    # PRONG 1 — Entity (supplier / logistics node names)
    # --------------------------------------------------
    for name in exposure.get("suppliers", []):
        _add(name)

    for name in exposure.get("logistics_nodes", []):
        _add(name)

    # --------------------------------------------------
    # PRONG 2 — Geo (city + disruption terms)
    # --------------------------------------------------
    cities_map = exposure.get("cities", {})
    for country, city_list in cities_map.items():
        # Search at most 3 cities per country to avoid query explosion
        for city in city_list[:3]:
            for q in _geo_prong(city, country, all_terms):
                _add(q)

    # Also add any port city that isn't already covered
    for port_key, port_rec in exposure.get("port_records", {}).items():
        city    = port_rec.get("city", "")
        country = port_rec.get("country", "")
        if city and city not in str(cities_map.get(country, [])):
            for q in _geo_prong(city, country, all_terms):
                _add(q)

    # --------------------------------------------------
    # PRONG 3 — Commodity (material + disruption terms)
    # --------------------------------------------------
    mat_records = exposure.get("material_records", {})
    for mat_key in exposure.get("materials", []):
        rec = mat_records.get(mat_key)
        if rec:
            for q in _commodity_prongs(mat_key, rec):
                _add(q)
        else:
            # Fallback for unrecognised materials: simple name + shortage
            _add(f'"{mat_key}" AND (shortage OR "supply disruption" OR "price surge")')

    # --------------------------------------------------
    # PRONG 4 — Route / chokepoint (strategic routes)
    # --------------------------------------------------
    for route_key, route_rec in exposure.get("route_records", {}).items():
        for qt in route_rec.get("query_terms", []):
            _add(qt)

    return queries
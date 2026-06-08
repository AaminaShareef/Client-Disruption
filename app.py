from flask import Flask, request, jsonify, render_template
from datetime import datetime
import os
import json
import logging

# ==========================================
# LOGGING
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s"
)
logger = logging.getLogger(__name__)

# ==========================================
# IMPORT UTILITIES
# ==========================================

from utils.query_generator import (
    build_exposure_map,
    generate_queries
)

from utils.rss_fetcher import (
    fetch_articles_for_country,
    fetch_articles_for_queries,
    clear_seen_urls
)

from utils.newsapi_fetcher import (
    fetch_newsapi_for_country,
    fetch_newsapi_for_queries,
    clear_seen_urls as newsapi_clear_seen_urls,
)

from utils.relevance_scorer import (
    score_articles
)

from utils.rss_sources import (
    get_sources_for_country
)

app = Flask(__name__)

# ==========================================
# CONFIG
# ==========================================

CLIENT_DIR = "data/clients"
os.makedirs(CLIENT_DIR, exist_ok=True)

# Max queries fired against Google News RSS per analysis run.
# Entity prongs (supplier names) go first — highest signal density.
MAX_QUERY_FETCHES = 15

# Max queries sent to NewsAPI per run (each costs 1 API credit).
# Keep conservative — free tier is 100/day, developer is 500/day.
MAX_NEWSAPI_QUERIES = 5

# ==========================================
# SAVE CLIENT PROFILE
# ==========================================

def save_client_profile(profile):

    client_name = profile.get(
        "client_name",
        "unknown_client"
    )

    filename = (
        client_name
        .lower()
        .replace(" ", "_")
    )

    filepath = os.path.join(
        CLIENT_DIR,
        f"{filename}.json"
    )

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=4, ensure_ascii=False)

    return filepath

# ==========================================
# GEOGRAPHIC SOURCE VIEW
# (builds the response payload for the UI source panel)
# ==========================================

def build_geographic_sources(exposure):
    """
    Returns a dict of {country: [source_name, ...]} for the frontend
    to display which outlets are being monitored per country.
    """
    geo_sources = {}

    for country in exposure.get("countries", []):
        sources = get_sources_for_country(country)
        geo_sources[country] = [
            {
                "name":       s.get("name", ""),
                "category":   s.get("category", ""),
                "trust_score": s.get("trust_score", 0.65),
                "type":       s.get("type", "rss"),
            }
            for s in sources
        ]

    return geo_sources

# ==========================================
# PER-NODE RISK SUMMARY
# ==========================================

def build_node_risk_summary(scored_articles, exposure):
    """
    Aggregate per-node risk from scored articles.

    Returns a dict:
    {
      "suppliers":  { "TSMC": {"high": 2, "medium": 1, "low": 0, "top_score": 88} },
      "materials":  { "semiconductors": {...} },
      "ports":      { "Port of Kaohsiung": {...} },
      "routes":     { "Taiwan Strait": {...} },
    }
    """
    node_types = {
        "suppliers":  exposure.get("suppliers",       []),
        "materials":  exposure.get("materials",        []),
        "ports":      exposure.get("ports",            []),
        "routes":     exposure.get("routes",           []),
    }

    summary = {nt: {} for nt in node_types}

    # Initialise counters
    for node_type, node_list in node_types.items():
        for node in node_list:
            summary[node_type][node] = {
                "high": 0, "medium": 0, "low": 0, "top_score": 0
            }

    # Walk articles and credit linked nodes
    for article in scored_articles:
        level = article.get("impact_level", "LOW").lower()
        score = article.get("relevance_score", 0)

        for linked in article.get("linked_nodes", []):
            # linked_nodes format: "type:name"
            parts = linked.split(":", 1)
            if len(parts) != 2:
                continue
            node_type_tag, node_name = parts[0] + "s", parts[1]

            if node_type_tag in summary and node_name in summary[node_type_tag]:
                summary[node_type_tag][node_name][level] += 1
                if score > summary[node_type_tag][node_name]["top_score"]:
                    summary[node_type_tag][node_name]["top_score"] = score

    return summary

# ==========================================
# HOME
# ==========================================

@app.route("/")
def home():
    return render_template("index.html")

# ==========================================
# ANALYZE
# ==========================================

@app.route("/analyze", methods=["POST"])
def analyze():

    try:

        profile = request.json

        # ------------------------------
        # Save Client Profile
        # ------------------------------

        save_client_profile(profile)

        # ------------------------------
        # Exposure Mapping
        # ------------------------------

        exposure = build_exposure_map(profile)

        logger.info(
            f"Exposure map built — "
            f"countries={len(exposure['countries'])} "
            f"materials={len(exposure['materials'])} "
            f"ports={len(exposure['ports'])} "
            f"routes={len(exposure['routes'])}"
        )

        # ------------------------------
        # Query Generation
        # ------------------------------

        queries = generate_queries(exposure)

        logger.info(f"Generated {len(queries)} queries")

        # ------------------------------
        # Geographic Source View
        # ------------------------------

        geographic_sources = build_geographic_sources(exposure)

        # ------------------------------
        # Fetch Articles
        # (reset dedup store for this run)
        # ------------------------------

        clear_seen_urls()
        newsapi_clear_seen_urls()
        all_articles = []

        # Phase 1 — Country-level RSS sources (local + gov + wires)
        for country in exposure.get("countries", []):
            try:
                articles = fetch_articles_for_country(country)
                all_articles.extend(articles)
                logger.info(
                    f"Country fetch [{country}]: {len(articles)} articles"
                )
            except Exception as e:
                logger.warning(f"Country fetch error [{country}]: {e}")

        # Phase 2 — Three-prong queries via Google News RSS
        # Entity prongs first (highest precision), then geo, then commodity.
        # Slice to MAX_QUERY_FETCHES so we don't hammer the endpoint.
        try:
            query_articles = fetch_articles_for_queries(
                queries,
                max_queries=MAX_QUERY_FETCHES
            )
            all_articles.extend(query_articles)
            logger.info(f"Query fetch (RSS): {len(query_articles)} articles")
        except Exception as e:
            logger.warning(f"Query fetch error (RSS): {e}")

        # Phase 3 — NewsAPI country-level broad queries
        # One request per country; catches signals the geo prongs might miss.
        for country in exposure.get("countries", []):
            try:
                na_country = fetch_newsapi_for_country(country)
                all_articles.extend(na_country)
                if na_country:
                    logger.info(
                        f"NewsAPI country [{country}]: {len(na_country)} articles"
                    )
            except Exception as e:
                logger.warning(f"NewsAPI country error [{country}]: {e}")

        # Phase 4 — NewsAPI targeted queries (entity + commodity prongs)
        # Use entity and commodity prongs only — highest value for API credits.
        # Skip geo prongs (already covered by Phase 3 above).
        entity_and_commodity_queries = [
            q for q in queries
            if not ('"' in q and ' AND (' in q and
                    any(city_term in q.lower() for city_term in
                        [c.lower() for cities in exposure.get("cities", {}).values()
                         for c in cities[:3]]))
        ]
        try:
            na_query_articles = fetch_newsapi_for_queries(
                entity_and_commodity_queries,
                max_queries=MAX_NEWSAPI_QUERIES,
            )
            all_articles.extend(na_query_articles)
            if na_query_articles:
                logger.info(f"NewsAPI queries: {len(na_query_articles)} articles")
        except Exception as e:
            logger.warning(f"NewsAPI query fetch error: {e}")

        logger.info(f"Total raw articles: {len(all_articles)}")

        # ------------------------------
        # Score Articles
        # ------------------------------

        scored_articles = score_articles(all_articles, exposure)

        # ------------------------------
        # Per-Node Risk Summary
        # ------------------------------

        node_risk = build_node_risk_summary(scored_articles, exposure)

        # ------------------------------
        # Overall Risk Calculation
        # ------------------------------

        high_count   = sum(
            1 for a in scored_articles if a.get("impact_level") == "HIGH"
        )
        medium_count = sum(
            1 for a in scored_articles if a.get("impact_level") == "MEDIUM"
        )

        # Weighted risk score (capped at 100)
        risk_score = min(high_count * 20 + medium_count * 10, 100)

        # Overall level considers both article counts and node coverage
        nodes_at_high_risk = sum(
            1
            for node_type in node_risk.values()
            for node_data in node_type.values()
            if node_data["high"] >= 1
        )

        if high_count >= 5 or nodes_at_high_risk >= 3:
            overall_risk = "HIGH"
            risk_message = (
                "Multiple high-impact disruptions detected "
                "across supply chain exposure. Immediate review recommended."
            )
        elif high_count >= 1 or nodes_at_high_risk >= 1:
            overall_risk = "MEDIUM"
            risk_message = (
                "Potentially disruptive events detected affecting "
                "one or more supply chain nodes. Monitor closely."
            )
        else:
            overall_risk = "LOW"
            risk_message = (
                "No significant disruption signals detected currently."
            )

        # ------------------------------
        # Response
        # ------------------------------

        # Strip internal-only fields from exposure before sending
        # (material_records, port_records, route_records are large and
        #  only needed by the scorer — don't bloat the response)
        exposure_for_response = {
            k: v for k, v in exposure.items()
            if k not in ("material_records", "port_records", "route_records")
        }

        response = {

            "status":             "success",

            "client_name":        profile.get(
                                      "client_name", "Unknown Client"
                                  ),

            "analysis_timestamp": datetime.now().strftime(
                                      "%Y-%m-%d %H:%M:%S"
                                  ),

            "overall_risk":       overall_risk,
            "risk_message":       risk_message,
            "risk_score":         risk_score,

            "exposure_map":       exposure_for_response,

            "node_risk":          node_risk,

            "stats": {
                "suppliers_count":      len(profile.get("tier1_suppliers",  [])),
                "materials_count":      len(profile.get("raw_materials",    [])),
                "logistics_nodes_count": len(profile.get("logistics_nodes", [])),
                "total_articles":       len(all_articles),
                "scored_articles":      len(scored_articles),
                "critical_alerts":      0,
                "high_alerts":          high_count,
                "medium_alerts":        medium_count,
            },

            "query_breakdown": {
                "Countries":        len(exposure.get("countries",  [])),
                "Materials":        len(exposure.get("materials",  [])),
                "Ports":            len(exposure.get("ports",      [])),
                "Routes":           len(exposure.get("routes",     [])),
                "Suppliers":        len(exposure.get("suppliers",  [])),
                "Generated Queries": len(queries),
            },

            "queries":            queries[:50],

            "geographic_sources": geographic_sources,

            "news":               scored_articles[:30],
        }

        return jsonify(response)

    except Exception as e:
        logger.exception("Error in /analyze")
        return jsonify({
            "status":  "error",
            "message": str(e)
        }), 500

# ==========================================
# RUN
# ==========================================

if __name__ == "__main__":
    app.run(debug=True, port=5000)
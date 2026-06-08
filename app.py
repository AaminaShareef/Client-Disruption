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
MAX_QUERY_FETCHES = 15

# Max queries sent to NewsAPI per run.
MAX_NEWSAPI_QUERIES = 5

# ==========================================
# SAVE CLIENT PROFILE
# ==========================================

def save_client_profile(profile):
    client_name = profile.get("client_name", "unknown_client")
    filename = client_name.lower().replace(" ", "_")
    filepath = os.path.join(CLIENT_DIR, f"{filename}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=4, ensure_ascii=False)
    return filepath

# ==========================================
# GEOGRAPHIC SOURCE VIEW
# ==========================================

def build_geographic_sources(exposure):
    geo_sources = {}
    for country in exposure.get("countries", []):
        sources = get_sources_for_country(country)
        geo_sources[country] = [
            {
                "name":        s.get("name", ""),
                "category":    s.get("category", ""),
                "trust_score": s.get("trust_score", 0.65),
                "type":        s.get("type", "rss"),
            }
            for s in sources
        ]
    return geo_sources

# ==========================================
# PER-NODE RISK SUMMARY
# ==========================================

def build_node_risk_summary(scored_articles, exposure):
    node_types = {
        "suppliers": exposure.get("suppliers", []),
        "materials": exposure.get("materials", []),
        "ports":     exposure.get("ports",     []),
        "routes":    exposure.get("routes",    []),
    }
    summary = {nt: {} for nt in node_types}
    for node_type, node_list in node_types.items():
        for node in node_list:
            summary[node_type][node] = {
                "high": 0, "medium": 0, "low": 0, "top_score": 0
            }
    for article in scored_articles:
        level = article.get("impact_level", "LOW").lower()
        score = article.get("relevance_score", 0)
        for linked in article.get("linked_nodes", []):
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
# LIST SAVED CLIENT PROFILES
# GET /clients
# Returns: [{ id, client_name, saved_at, supplier_count, material_count }, ...]
# ==========================================

@app.route("/clients", methods=["GET"])
def list_clients():
    try:
        profiles = []
        for fname in sorted(os.listdir(CLIENT_DIR)):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(CLIENT_DIR, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                mtime = os.path.getmtime(fpath)
                profiles.append({
                    "id":              fname[:-5],           # filename without .json
                    "client_name":     data.get("client_name", fname[:-5]),
                    "saved_at":        datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
                    "supplier_count":  len(data.get("tier1_suppliers", [])),
                    "material_count":  len(data.get("raw_materials",   [])),
                    "logistics_count": len(data.get("logistics_nodes", [])),
                    "facility_count":  len(data.get("own_facilities",  [])),
                })
            except Exception as e:
                logger.warning(f"Could not read client file {fname}: {e}")
        return jsonify({"status": "success", "profiles": profiles})
    except Exception as e:
        logger.exception("Error in GET /clients")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==========================================
# LOAD A SINGLE CLIENT PROFILE
# GET /clients/<client_id>
# Returns the full profile JSON
# ==========================================

@app.route("/clients/<client_id>", methods=["GET"])
def get_client(client_id):
    try:
        # Sanitise — only allow safe filename characters
        safe_id = "".join(c for c in client_id if c.isalnum() or c in ("_", "-"))
        fpath = os.path.join(CLIENT_DIR, f"{safe_id}.json")
        if not os.path.exists(fpath):
            return jsonify({"status": "error", "message": "Profile not found"}), 404
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify({"status": "success", "profile": data})
    except Exception as e:
        logger.exception(f"Error in GET /clients/{client_id}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==========================================
# DELETE A CLIENT PROFILE
# DELETE /clients/<client_id>
# ==========================================

@app.route("/clients/<client_id>", methods=["DELETE"])
def delete_client(client_id):
    try:
        safe_id = "".join(c for c in client_id if c.isalnum() or c in ("_", "-"))
        fpath = os.path.join(CLIENT_DIR, f"{safe_id}.json")
        if not os.path.exists(fpath):
            return jsonify({"status": "error", "message": "Profile not found"}), 404
        os.remove(fpath)
        logger.info(f"Deleted client profile: {safe_id}.json")
        return jsonify({"status": "success", "message": f"{safe_id} deleted"})
    except Exception as e:
        logger.exception(f"Error in DELETE /clients/{client_id}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==========================================
# SAVE PROFILE (without running analysis)
# POST /save_profile
# Body: same JSON schema as /analyze payload
# ==========================================

@app.route("/save_profile", methods=["POST"])
def save_profile_route():
    try:
        profile = request.json
        if not profile or not profile.get("client_name", "").strip():
            return jsonify({"status": "error", "message": "client_name is required"}), 400
        filepath = save_client_profile(profile)
        logger.info(f"Profile saved via /save_profile: {filepath}")
        return jsonify({"status": "success", "message": f"Profile saved to {filepath}"})
    except Exception as e:
        logger.exception("Error in /save_profile")
        return jsonify({"status": "error", "message": str(e)}), 500

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
        # ------------------------------

        clear_seen_urls()
        newsapi_clear_seen_urls()
        all_articles = []

        # Phase 1 — Country-level RSS sources
        for country in exposure.get("countries", []):
            try:
                articles = fetch_articles_for_country(country)
                all_articles.extend(articles)
                logger.info(f"Country fetch [{country}]: {len(articles)} articles")
            except Exception as e:
                logger.warning(f"Country fetch error [{country}]: {e}")

        # Phase 2 — Three-prong queries via Google News RSS
        try:
            query_articles = fetch_articles_for_queries(
                queries, max_queries=MAX_QUERY_FETCHES
            )
            all_articles.extend(query_articles)
            logger.info(f"Query fetch (RSS): {len(query_articles)} articles")
        except Exception as e:
            logger.warning(f"Query fetch error (RSS): {e}")

        # Phase 3 — NewsAPI country-level broad queries
        for country in exposure.get("countries", []):
            try:
                na_country = fetch_newsapi_for_country(country)
                all_articles.extend(na_country)
                if na_country:
                    logger.info(f"NewsAPI country [{country}]: {len(na_country)} articles")
            except Exception as e:
                logger.warning(f"NewsAPI country error [{country}]: {e}")

        # Phase 4 — NewsAPI targeted queries
        entity_and_commodity_queries = [
            q for q in queries
            if not ('"' in q and ' AND (' in q and
                    any(city_term in q.lower() for city_term in
                        [c.lower() for cities in exposure.get("cities", {}).values()
                         for c in cities[:3]]))
        ]
        try:
            na_query_articles = fetch_newsapi_for_queries(
                entity_and_commodity_queries, max_queries=MAX_NEWSAPI_QUERIES,
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

        high_count   = sum(1 for a in scored_articles if a.get("impact_level") == "HIGH")
        medium_count = sum(1 for a in scored_articles if a.get("impact_level") == "MEDIUM")

        risk_score = min(high_count * 20 + medium_count * 10, 100)

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
            risk_message = "No significant disruption signals detected currently."

        # ------------------------------
        # Response
        # ------------------------------

        exposure_for_response = {
            k: v for k, v in exposure.items()
            if k not in ("material_records", "port_records", "route_records")
        }

        response = {
            "status":             "success",
            "client_name":        profile.get("client_name", "Unknown Client"),
            "analysis_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "overall_risk":       overall_risk,
            "risk_message":       risk_message,
            "risk_score":         risk_score,
            "exposure_map":       exposure_for_response,
            "node_risk":          node_risk,
            "stats": {
                "suppliers_count":       len(profile.get("tier1_suppliers",  [])),
                "materials_count":       len(profile.get("raw_materials",    [])),
                "logistics_nodes_count": len(profile.get("logistics_nodes",  [])),
                "total_articles":        len(all_articles),
                "scored_articles":       len(scored_articles),
                "critical_alerts":       0,
                "high_alerts":           high_count,
                "medium_alerts":         medium_count,
            },
            "query_breakdown": {
                "Countries":         len(exposure.get("countries",  [])),
                "Materials":         len(exposure.get("materials",  [])),
                "Ports":             len(exposure.get("ports",      [])),
                "Routes":            len(exposure.get("routes",     [])),
                "Suppliers":         len(exposure.get("suppliers",  [])),
                "Generated Queries": len(queries),
            },
            "queries":            queries[:50],
            "geographic_sources": geographic_sources,
            "news":               scored_articles[:30],
        }

        return jsonify(response)

    except Exception as e:
        logger.exception("Error in /analyze")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==========================================
# RUN
# ==========================================

if __name__ == "__main__":
    app.run(debug=True, port=5000)
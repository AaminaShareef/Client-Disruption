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

from utils.article_preprocessor import (
    preprocess_articles,
    preprocess_for_sbert,
    _get_nlp,           # imported so we can warm-load at startup
)

from utils.event_clusterer import cluster_articles, flatten_clusters
from utils.summariser import attach_summaries, summarise_article

from utils.sbert_encoder import (
    encode_articles,
    deduplicate_semantic,
    find_similar,
)

app = Flask(__name__)

# ── Numpy-safe JSON encoder ───────────────────────────────────────────────────
# Flask's default encoder can't handle numpy scalar types (np.int64, np.float32,
# np.bool_, np.ndarray) that leak out of DBSCAN / SBERT / scoring pipelines.
# This encoder coerces them transparently so jsonify() never raises TypeError.
import numpy as _np

class _NumpySafeEncoder(app.json_provider_class):
    def default(self, obj):
        if isinstance(obj, _np.integer):  return int(obj)
        if isinstance(obj, _np.floating): return float(obj)
        if isinstance(obj, _np.bool_):    return bool(obj)
        if isinstance(obj, _np.ndarray):  return obj.tolist()
        return super().default(obj)

app.json_provider_class = _NumpySafeEncoder
app.json = _NumpySafeEncoder(app)
# ─────────────────────────────────────────────────────────────────────────────

# ==========================================
# CONFIG
# ==========================================

CLIENT_DIR = "data/clients"
RUNS_DIR   = "data/runs"

os.makedirs(CLIENT_DIR, exist_ok=True)
os.makedirs(RUNS_DIR,   exist_ok=True)

# Max queries fired against Google News RSS per analysis run.
MAX_QUERY_FETCHES = 15

# Max queries sent to NewsAPI per run.
MAX_NEWSAPI_QUERIES = 5

# ==========================================
# WARM-LOAD spaCy AT STARTUP
# ─────────────────────────────────────────
# Loading spaCy lazily (inside the first /analyze request) causes
# Werkzeug's file-change watcher to detect thinc/spaCy internal
# files being imported and restart the server mid-request, which
# kills the in-flight fetch → "Failed to fetch" in the browser.
#
# Loading the model once here, before the server starts accepting
# requests, completely avoids that race condition.
# ==========================================

logger.info("Pre-loading spaCy model at startup…")
_get_nlp()
logger.info("spaCy model ready.")

logger.info("Pre-loading SBERT model at startup…")
from utils.sbert_encoder import _get_model as _get_sbert_model, _get_archetype_embeddings
_get_sbert_model()
_get_archetype_embeddings()
logger.info("SBERT model ready.")

# ==========================================
# SAVE CLIENT PROFILE
# ==========================================

def save_client_profile(profile):
    client_name = profile.get("client_name", "unknown_client")
    filename = client_name.lower().replace(" ", "_")
    filename = "".join(c for c in filename if c.isalnum() or c in ("_", "-"))
    filepath = os.path.join(CLIENT_DIR, f"{filename}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=4, ensure_ascii=False)
    return filepath

# ==========================================
# SAVE PREPROCESSED RUN DATA
# ==========================================

def _run_filename_base(client_name: str, timestamp: str) -> str:
    """
    Build a safe base filename for a run:
        apple_inc_20240403_143022
    """
    safe_name = client_name.lower().replace(" ", "_")
    safe_name = "".join(c for c in safe_name if c.isalnum() or c in ("_", "-"))
    safe_ts   = timestamp.replace(" ", "_").replace(":", "").replace("-", "")
    return f"{safe_name}_{safe_ts}"


def save_preprocessed_run(
    client_name:  str,
    timestamp:    str,
    preprocessed: list,
    exposure:     dict,
    overall_risk: str,
    risk_score:   int,
) -> dict:
    """
    Persist two artefacts for every analysis run:

    1.  data/runs/<base>_preprocessed.json
        Full preprocessed article objects (all four pipeline stages).
        Used for debugging, offline inspection and retraining.

    2.  data/runs/<base>_sbert_corpus.jsonl
        One JSON line per article — only the fields needed by
        SentenceTransformer.encode() and downstream ML.

    Returns a dict with the two saved paths (or error messages).
    """
    base   = _run_filename_base(client_name, timestamp)
    result = {}

    # ── 1. Full preprocessed JSON ──────────────────────────────────
    full_path = os.path.join(RUNS_DIR, f"{base}_preprocessed.json")
    try:
        payload = {
            "client_name":   client_name,
            "run_timestamp": timestamp,
            "overall_risk":  overall_risk,
            "risk_score":    risk_score,
            "exposure_map":  {
                k: v for k, v in exposure.items()
                if k not in ("material_records", "port_records", "route_records")
            },
            "article_count": len(preprocessed),
            "articles":      preprocessed,
        }
        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved full preprocessed run → {full_path}")
        result["preprocessed_path"] = full_path
    except Exception as e:
        logger.error(f"Failed to save full preprocessed run: {e}")
        result["preprocessed_path"] = f"ERROR: {e}"

    # ── 2. SBERT corpus JSONL ──────────────────────────────────────
    sbert_path = os.path.join(RUNS_DIR, f"{base}_sbert_corpus.jsonl")
    try:
        with open(sbert_path, "w", encoding="utf-8") as f:
            for art in preprocessed:
                line = {
                    # Core SBERT fields
                    "input_text":       art.get("input_text",        ""),
                    "input_text_w_ent": art.get("input_text_w_ent",  ""),
                    "entity_string":    art.get("entity_string",     ""),
                    "token_estimate":   art.get("token_estimate",    0),
                    # NER output
                    "sentences":        art.get("sentences",         []),
                    "ner_entities":     art.get("ner_entities",      []),
                    # Scoring labels (useful for supervised fine-tuning)
                    "impact_level":     art.get("impact_level",      "LOW"),
                    "relevance_score":  art.get("relevance_score",   0),
                    # Provenance
                    "clean_title":      art.get("clean_title",       ""),
                    "url":              art.get("url",               ""),
                    "source":           art.get("source",            ""),
                    "published":        art.get("published",         ""),
                    "linked_nodes":     art.get("linked_nodes",      []),
                    "preprocessing_ok": art.get("preprocessing_ok",  False),
                }
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        logger.info(f"Saved SBERT corpus JSONL → {sbert_path}")
        result["sbert_corpus_path"] = sbert_path
    except Exception as e:
        logger.error(f"Failed to save SBERT corpus JSONL: {e}")
        result["sbert_corpus_path"] = f"ERROR: {e}"

    return result


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
                    "id":              fname[:-5],
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
# ==========================================

@app.route("/clients/<client_id>", methods=["GET"])
def get_client(client_id):
    try:
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
# LIST SAVED RUNS
# GET /runs?client=<name>
# ==========================================

@app.route("/runs", methods=["GET"])
def list_runs():
    """
    Return a summary of all saved analysis runs.
    Optionally filter by ?client=apple_inc
    """
    try:
        client_filter = request.args.get("client", "").lower().strip()
        runs = []
        for fname in sorted(os.listdir(RUNS_DIR), reverse=True):
            if not fname.endswith("_preprocessed.json"):
                continue
            if client_filter and not fname.startswith(client_filter):
                continue
            fpath = os.path.join(RUNS_DIR, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                base         = fname.replace("_preprocessed.json", "")
                sbert_fname  = f"{base}_sbert_corpus.jsonl"
                sbert_exists = os.path.exists(os.path.join(RUNS_DIR, sbert_fname))
                runs.append({
                    "run_id":            base,
                    "client_name":       data.get("client_name", ""),
                    "run_timestamp":     data.get("run_timestamp", ""),
                    "overall_risk":      data.get("overall_risk", ""),
                    "risk_score":        data.get("risk_score", 0),
                    "article_count":     data.get("article_count", 0),
                    "preprocessed_file": fname,
                    "sbert_file":        sbert_fname if sbert_exists else None,
                    "file_size_kb":      round(os.path.getsize(fpath) / 1024, 1),
                })
            except Exception as e:
                logger.warning(f"Could not read run file {fname}: {e}")
        return jsonify({"status": "success", "runs": runs, "total": len(runs)})
    except Exception as e:
        logger.exception("Error in GET /runs")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==========================================
# ANALYZE
# ==========================================

@app.route("/analyze", methods=["POST"])
def analyze():

    try:

        profile = request.json

        # ─────────────────────────────────────────────────────────
        # Normalise tier1_suppliers so the saved profile always
        # contains both `material` AND `location` fields regardless
        # of which schema variant the frontend sent.
        # ─────────────────────────────────────────────────────────
        normalised_suppliers = []
        for s in profile.get("tier1_suppliers", []):
            normalised_suppliers.append({
                "name":     s.get("name",     ""),
                "material": s.get("material", ""),
                "location": s.get("location") or s.get("country") or s.get("city") or "",
                "country":  s.get("country")  or s.get("location") or "",
                "city":     s.get("city",     ""),
            })
        profile["tier1_suppliers"] = normalised_suppliers

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
        # NLP Preprocessing (server-side)
        # spaCy is already loaded (warm-loaded at startup), so this
        # call will NOT trigger a Werkzeug reload.
        # ------------------------------
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            preprocessed_articles = preprocess_articles(scored_articles, exposure)
        except Exception as e:
            logger.warning(f"Preprocessing pipeline error: {e} — falling back to scored articles")
            preprocessed_articles = scored_articles

        # ------------------------------
        # Semantic Encoding (SBERT)
        # Runs after NLP preprocessing; produces doc_embedding on every
        # article and removes near-duplicate stories before clustering.
        # Falls back gracefully if sentence-transformers is not installed.
        # ------------------------------
        try:
            encoding_result  = encode_articles(preprocessed_articles)
            sbert_articles   = encoding_result.articles   # dicts now have doc_embedding

            # Semantic deduplication — remove near-identical news stories
            deduped_articles = deduplicate_semantic(encoding_result, threshold=0.88)
            logger.info(
                f"SBERT dedup: {len(sbert_articles)} → {len(deduped_articles)} articles"
            )

            # event_clusterer expects the embedding under the key "embedding";
            # sbert_encoder stores it as "doc_embedding" → copy the key.
            for art in deduped_articles:
                art["embedding"] = art.get("doc_embedding")

        except Exception as e:
            logger.warning(f"SBERT encoding failed (non-fatal): {e} — skipping.")
            deduped_articles = preprocessed_articles
            # Ensure the key exists so clusterer doesn't crash
            for art in deduped_articles:
                art.setdefault("embedding", None)

        # ------------------------------
        # Event Clustering (DBSCAN on SBERT embeddings)
        # Groups semantically similar articles into real-world events.
        # Falls back to per-article singletons if embeddings are absent
        # or scikit-learn is not installed.
        # ------------------------------
        try:
            clusters = cluster_articles(deduped_articles)
            attach_summaries(clusters, per_article=True)
            for cluster in clusters:
                for art in cluster["articles"]:
                    art["cluster_id"]      = cluster["cluster_id"]
                    art["cluster_size"]    = cluster["article_count"]
                    art["cluster_summary"] = cluster.get("summary", "")
            logger.info(
                f"Clustering: {len(clusters)} cluster(s) from "
                f"{len(deduped_articles)} article(s)"
            )
        except Exception as e:
            logger.warning(f"Event clustering failed (non-fatal): {e} — skipping.")
            clusters = []

        # ------------------------------
        # Per-article summaries (fallback for articles that skipped clustering)
        # ------------------------------
        for art in deduped_articles:
            if "summary" not in art:
                try:
                    art["summary"] = summarise_article(art)
                except Exception:
                    art["summary"] = art.get("clean_title", "")

        # ------------------------------
        # Per-Node Risk Summary
        # ------------------------------
        node_risk = build_node_risk_summary(deduped_articles, exposure)

        # ------------------------------
        # Overall Risk Calculation
        # ------------------------------
        high_count   = sum(1 for a in deduped_articles if a.get("impact_level") == "HIGH")
        medium_count = sum(1 for a in deduped_articles if a.get("impact_level") == "MEDIUM")

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
        # Save Preprocessed Run to Disk
        # Errors here are non-fatal — logged but never abort the response.
        # ------------------------------
        run_save_result = {}
        try:
            run_save_result = save_preprocessed_run(
                client_name  = profile.get("client_name", "unknown"),
                timestamp    = timestamp,
                preprocessed = deduped_articles,
                exposure     = exposure,
                overall_risk = overall_risk,
                risk_score   = risk_score,
            )
        except Exception as e:
            logger.error(f"Run save failed (non-fatal): {e}")
            run_save_result = {"error": str(e)}

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
            "analysis_timestamp": timestamp,
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
                "preprocessed_articles": len(preprocessed_articles),
                "deduplicated_articles": len(deduped_articles),
                "event_clusters":        len([c for c in clusters if not c.get("is_noise")]),
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
            "news":               deduped_articles[:30],
            "clusters":           [
                {
                    "cluster_id":    c["cluster_id"],
                    "is_noise":      c["is_noise"],
                    "article_count": c["article_count"],
                    "impact_level":  c["impact_level"],
                    "risk_score":    c["risk_score"],
                    "linked_nodes":  c["linked_nodes"],
                    "sources":       c["sources"],
                    "summary":       c.get("summary", ""),
                    "article_urls":  [a.get("url", "") for a in c["articles"]],
                }
                for c in clusters
            ],
            "run_saved":          run_save_result,
        }

        return jsonify(response)

    except Exception as e:
        logger.exception("Error in /analyze")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==========================================
# RUN
# ─────────────────────────────────────────
# use_reloader=False  — CRITICAL on Windows with spaCy/thinc.
#
# Werkzeug's reloader watches all imported Python files for changes.
# When spaCy loads its model it imports thinc internals; on Windows
# the watchdog backend detects these as "changed" and immediately
# restarts the server, killing any in-flight request mid-execution
# and producing "Failed to fetch" in the browser.
#
# use_reloader=False disables that watcher entirely. You can still
# use debug=True for the interactive debugger / detailed tracebacks.
# Simply restart the server manually (Ctrl+C → python app.py) when
# you make code changes during development.
# ==========================================

if __name__ == "__main__":
    app.run(
        debug=True,
        port=5000,
        use_reloader=False,   # ← prevents thinc/spaCy from triggering a mid-request restart
    )
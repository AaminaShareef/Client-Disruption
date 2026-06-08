"""
SBERT INTEGRATION PATCH
========================
How to wire sbert_encoder.py into app.py.

Step 1 — Add to imports (top of app.py)
----------------------------------------

from utils.sbert_encoder import (
    encode_articles,
    deduplicate_semantic,
    find_similar,
)


Step 2 — Warm-load SBERT at startup (alongside spaCy)
-------------------------------------------------------
Add these two lines right after the spaCy warm-load block in app.py:

    logger.info("Pre-loading SBERT model at startup…")
    from utils.sbert_encoder import _get_model, _get_archetype_embeddings
    _get_model()
    _get_archetype_embeddings()
    logger.info("SBERT model ready.")


Step 3 — Insert SBERT encoding after preprocessing in /analyze
----------------------------------------------------------------
Find this block in the /analyze route (after preprocessing):

    # -- Per-Node Risk Summary --
    node_risk = build_node_risk_summary(preprocessed_articles, exposure)

REPLACE with:

    # -- Semantic Encoding (SBERT) --
    try:
        encoding_result = encode_articles(preprocessed_articles)
        sbert_articles  = encoding_result.articles          # enriched with semantic fields

        # Semantic deduplication — remove near-duplicate news stories
        deduped_articles = deduplicate_semantic(encoding_result, threshold=0.88)
        logger.info(
            f"SBERT dedup: {len(sbert_articles)} → {len(deduped_articles)} articles"
        )
    except Exception as e:
        logger.warning(f"SBERT encoding failed (non-fatal): {e}")
        deduped_articles = preprocessed_articles     # graceful fallback

    # -- Per-Node Risk Summary (use deduped articles) --
    node_risk = build_node_risk_summary(deduped_articles, exposure)


Step 4 — Update risk calculation to use deduped articles
---------------------------------------------------------
Change:
    high_count   = sum(1 for a in preprocessed_articles if a.get("impact_level") == "HIGH")
    medium_count = sum(1 for a in preprocessed_articles if a.get("impact_level") == "MEDIUM")

To:
    high_count   = sum(1 for a in deduped_articles if a.get("impact_level") == "HIGH")
    medium_count = sum(1 for a in deduped_articles if a.get("impact_level") == "MEDIUM")


Step 5 — Pass deduped_articles through save and response
---------------------------------------------------------
Update save_preprocessed_run() call:
    preprocessed = deduped_articles,   # was: preprocessed_articles

Update response dict:
    "news":   deduped_articles[:30],   # was: preprocessed_articles[:30]
    "stats": {
        ...
        "preprocessed_articles": len(preprocessed_articles),
        "deduplicated_articles": len(deduped_articles),   # new field
        ...
    }


Step 6 — Optional semantic search endpoint
-------------------------------------------
Add this route to app.py for dashboard semantic search:

@app.route("/search", methods=["POST"])
def semantic_search():
    \"\"\"
    POST body: { "query": "port closure China", "run_id": "..." }
    Loads the run's preprocessed JSON, re-encodes, and returns top-5 matches.
    \"\"\"
    try:
        body     = request.json
        query    = body.get("query", "").strip()
        run_id   = body.get("run_id", "").strip()

        if not query:
            return jsonify({"status": "error", "message": "query required"}), 400

        # Load saved run
        fpath = os.path.join(RUNS_DIR, f"{run_id}_preprocessed.json")
        if not os.path.exists(fpath):
            return jsonify({"status": "error", "message": "run not found"}), 404

        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)

        articles = data.get("articles", [])
        if not articles:
            return jsonify({"status": "success", "results": []})

        enc_result = encode_articles(articles)
        hits       = find_similar(query, enc_result, top_k=10)

        return jsonify({
            "status":  "success",
            "query":   query,
            "results": [
                {
                    "title":            h.get("clean_title") or h.get("title", ""),
                    "url":              h.get("url", ""),
                    "published":        h.get("published", ""),
                    "source":           h.get("source", ""),
                    "impact_level":     h.get("impact_level", "LOW"),
                    "relevance_score":  h.get("relevance_score", 0),
                    "similarity_score": h.get("similarity_score", 0.0),
                    "semantic_category": h.get("semantic_category", ""),
                }
                for h in hits
            ]
        })

    except Exception as e:
        logger.exception("Error in /search")
        return jsonify({"status": "error", "message": str(e)}), 500
"""

REQUIREMENTS_ADDITION = """
# Add to requirements.txt:
sentence-transformers>=2.7.0
"""
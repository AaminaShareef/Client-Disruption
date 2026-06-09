"""
utils/sbert_encoder.py
======================
Sentence-BERT semantic encoding layer for the Supply Chain
Disruption Intelligence System.

Sits immediately after article_preprocessor.py in the pipeline:

  rss_fetcher / newsapi_fetcher
        ↓
  relevance_scorer        (rule-based 0-100 score, impact_level)
        ↓
  article_preprocessor    (spaCy NER, sentence segmentation, input_text)
        ↓
  sbert_encoder  ← YOU ARE HERE
        ↓
  (future) clustering, deduplication, summarisation

Why SBERT over keyword search
------------------------------
Keyword matching treats "iron ore exports suspended" and
"ArcelorMittal warns of raw material shortage" as unrelated.
SBERT projects both into the same region of a 384-dimensional
embedding space so we can detect semantic equivalence, cluster
events, and find the closest known disruption archetype even
when surface vocabulary is completely different.

Three-level encoding strategy
------------------------------
  Level       Input unit          Purpose
  ─────────   ──────────────────  ───────────────────────────────────
  DOCUMENT    Full article text   Cluster similar articles (event
              (title + body)      deduplication, DBSCAN later)

  PARAGRAPH   Each paragraph /    Find the core paragraph — the one
              spaCy sentence      closest to the document centroid.
              group               Useful for abstractive summarisation.

  SENTENCE    Each sentence       Build a sentence-level corpus for
                                  LexRank / MMR extractive summary
                                  and unique data-point extraction.

All three levels are computed in one forward pass of batched
SentenceTransformer.encode() calls, sharing the loaded model.

Semantic similarity index
--------------------------
After encoding, we build a lightweight cosine-similarity search
index over document-level embeddings so callers can ask:

    "What past articles are semantically similar to this one?"
    "Which articles in this batch are near-duplicates?"

This is implemented with plain NumPy (no Faiss required) and is
fast enough for batches up to ~500 articles.

Disruption archetype matching
------------------------------
A small set of hard-coded "archetype" sentences covers the six
disruption categories from disruption_terms.json:
  - Port closure / congestion
  - Factory / plant shutdown
  - Labour action (strike, walkout)
  - Natural disaster (earthquake, flood, typhoon)
  - Geopolitical / sanctions
  - Commodity shortage / price spike

Each incoming article is matched against these archetypes; the
closest match gives a semantic disruption_category that is richer
than the rule-based domain hit from relevance_scorer.

Public API
----------
  encode_articles(preprocessed_articles, *, use_entity_augmented)
      Main entry point. Accepts list from preprocess_articles().
      Returns EncodingResult namedtuple.

  find_similar(query_text, encoding_result, top_k)
      Semantic search: returns top-k articles closest to query_text.

  deduplicate_semantic(encoding_result, threshold)
      Returns a deduplicated article list; near-duplicates
      (cosine similarity ≥ threshold) are merged/dropped.

Configuration (module-level constants)
---------------------------------------
  SBERT_MODEL           Model name passed to SentenceTransformer.
                        Default: "all-MiniLM-L6-v2" (fast, 384-dim).
  SBERT_BATCH_SIZE      Encode batch size (default 32).
  SBERT_MAX_SEQ_LEN     Hard truncation before encode (default 384 tokens).
  DEDUP_THRESHOLD       Cosine similarity above which articles are
                        considered near-duplicates (default 0.88).
  ARCHETYPE_TOP_K       How many archetype matches to keep per article
                        (default 2).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ==========================================
# CONFIGURATION
# ==========================================

SBERT_MODEL      = "all-MiniLM-L6-v2"   # 384-dim, ~80 MB, MIT licence
SBERT_BATCH_SIZE = 32
SBERT_MAX_SEQ_LEN = 384                  # truncate to stay within model limit
DEDUP_THRESHOLD  = 0.88                  # cosine sim ≥ this → near-duplicate
ARCHETYPE_TOP_K  = 2                     # archetype matches kept per article

# ==========================================
# DISRUPTION ARCHETYPES
# ==========================================
# These representative sentences anchor each disruption category in
# embedding space.  Chosen to be concise, domain-specific, and to
# cover the full vocabulary range within each category.

DISRUPTION_ARCHETYPES: dict[str, list[str]] = {
    "port_disruption": [
        "The port has been closed due to severe congestion and vessel queuing.",
        "Container throughput at the terminal fell sharply after the strike.",
        "Port operations are suspended following the typhoon making landfall.",
        "Ship berthing delays at the harbour are now exceeding five days.",
    ],
    "factory_shutdown": [
        "The manufacturing plant has halted production indefinitely.",
        "The semiconductor fabrication facility suspended wafer output.",
        "Factory output was cut after an explosion in the assembly line.",
        "Operations at the industrial site ceased following equipment failure.",
    ],
    "labour_action": [
        "Workers walked off the job in a strike over wage disputes.",
        "The union called a nationwide walkout disrupting logistics operations.",
        "Labour unrest at the facility has stopped production for three days.",
        "Dockworkers refused to unload vessels amid contract negotiations.",
    ],
    "natural_disaster": [
        "A major earthquake struck the manufacturing region causing structural damage.",
        "Severe flooding has inundated the industrial zone and halted logistics.",
        "The typhoon destroyed warehouses and disrupted port access roads.",
        "Wildfires forced the evacuation of workers and closure of the facility.",
    ],
    "geopolitical_sanctions": [
        "New export restrictions were imposed on semiconductor materials.",
        "Sanctions prevent the company from sourcing components from the supplier.",
        "Trade war tariffs have sharply increased the cost of imported raw materials.",
        "The government banned exports of critical minerals amid escalating tensions.",
    ],
    "commodity_shortage": [
        "Spot prices for lithium carbonate surged due to supply shortfall.",
        "Critical raw material inventories fell to a record low this quarter.",
        "Buyers are scrambling to secure alternative supply after the mine closure.",
        "Chip shortages continue to constrain automotive production globally.",
    ],
}

# ==========================================
# LAZY MODEL LOAD
# ==========================================

_model = None
_archetype_embeddings: Optional[dict[str, np.ndarray]] = None


def _get_model():
    """
    Load SentenceTransformer model once, lazily.

    Falls back gracefully if sentence-transformers is not installed so
    the rest of the pipeline can run without SBERT (embeddings will be
    None in that case).
    """
    global _model
    if _model is not None:
        return _model

    try:
        from sentence_transformers import SentenceTransformer
        logger.info(f"Loading SBERT model '{SBERT_MODEL}' …")
        t0 = time.time()
        _model = SentenceTransformer(SBERT_MODEL)
        _model.max_seq_length = SBERT_MAX_SEQ_LEN
        logger.info(
            f"SBERT model ready in {time.time()-t0:.1f}s  "
            f"(dim={_model.get_sentence_embedding_dimension()})"
        )
    except ImportError:
        logger.warning(
            "sentence-transformers not installed.  "
            "Run:  pip install sentence-transformers\n"
            "SBERT encoding will be skipped."
        )
        _model = None
    except Exception as e:
        logger.error(f"SBERT model load failed: {e}")
        _model = None

    return _model


def _get_archetype_embeddings() -> Optional[dict[str, np.ndarray]]:
    """
    Encode archetype sentences once and cache.
    Returns None if model unavailable.
    """
    global _archetype_embeddings
    if _archetype_embeddings is not None:
        return _archetype_embeddings

    model = _get_model()
    if model is None:
        return None

    _archetype_embeddings = {}
    for category, sentences in DISRUPTION_ARCHETYPES.items():
        emb = model.encode(
            sentences,
            batch_size=len(sentences),
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        # Store mean of the sentence embeddings as the category centroid
        _archetype_embeddings[category] = emb.mean(axis=0)

    logger.info(
        f"Archetype embeddings computed for "
        f"{len(_archetype_embeddings)} disruption categories."
    )
    return _archetype_embeddings


# ==========================================
# COSINE SIMILARITY HELPERS
# ==========================================

def _cosine_sim_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """
    Compute cosine similarity between every row of a and every row of b.
    Both a and b should already be L2-normalised (unit vectors).
    Returns shape (len(a), len(b)).
    """
    return np.dot(a, b.T)


def _cosine_sim_1d(vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """
    Compute cosine similarity between a single vector and each row
    of a matrix.  Both should be L2-normalised.
    Returns shape (len(matrix),).
    """
    return matrix.dot(vec)


# ==========================================
# PARAGRAPH GROUPING
# ==========================================

_PARAGRAPH_GROUP_SIZE = 3   # sentences per synthetic paragraph


def _group_sentences_into_paragraphs(sentences: list[str]) -> list[str]:
    """
    Group consecutive sentences into synthetic paragraphs of
    PARAGRAPH_GROUP_SIZE sentences each.

    This is used when the article has no natural paragraph breaks
    (common with RSS / NewsAPI snippets).  Grouping gives the
    paragraph encoder a meaningful chunk of context.
    """
    if not sentences:
        return []
    paragraphs = []
    for i in range(0, len(sentences), _PARAGRAPH_GROUP_SIZE):
        chunk = sentences[i:i + _PARAGRAPH_GROUP_SIZE]
        paragraphs.append(" ".join(chunk))
    return paragraphs


# ==========================================
# RESULT DATACLASS
# ==========================================

@dataclass
class ArticleEncoding:
    """
    All embedding artefacts for a single article.

    Attributes
    ----------
    article_idx         : Index in the original preprocessed list.
    doc_embedding       : 1-D float32 array, shape (dim,).
                          Document-level embedding (title + body).
    sentence_embeddings : 2-D float32 array, shape (n_sents, dim).
                          One row per sentence.
    paragraph_embeddings: 2-D float32 array, shape (n_paras, dim).
                          One row per synthetic paragraph.
    core_paragraph_idx  : Index of the paragraph closest to the
                          document centroid — most representative chunk.
    archetype_matches   : List of (category_name, cosine_score) tuples,
                          sorted descending.  Top-2 by default.
    semantic_category   : Best-matching archetype category name.
    semantic_score      : Cosine similarity to the best archetype.
    """
    article_idx:          int
    doc_embedding:        Optional[np.ndarray]    = None
    sentence_embeddings:  Optional[np.ndarray]    = None
    paragraph_embeddings: Optional[np.ndarray]    = None
    core_paragraph_idx:   int                     = 0
    archetype_matches:    list[tuple[str, float]] = field(default_factory=list)
    semantic_category:    str                     = "unknown"
    semantic_score:       float                   = 0.0


@dataclass
class EncodingResult:
    """
    Container returned by encode_articles().

    Attributes
    ----------
    articles            : Original preprocessed article dicts,
                          each enriched with SBERT fields.
    encodings           : Parallel list of ArticleEncoding objects.
    doc_embeddings      : 2-D array of all document embeddings,
                          shape (n_articles, dim).  None if SBERT unavailable.
    model_name          : SBERT model identifier string.
    embedding_dim       : Dimensionality of embeddings.
    encode_time_s       : Wall-clock seconds for the encoding step.
    sbert_available     : False when sentence-transformers is missing.
    """
    articles:        list[dict]
    encodings:       list[ArticleEncoding]
    doc_embeddings:  Optional[np.ndarray]
    model_name:      str
    embedding_dim:   int
    encode_time_s:   float
    sbert_available: bool


# ==========================================
# ARCHETYPE MATCHING
# ==========================================

def _match_archetypes(
    doc_emb: np.ndarray,
    top_k:   int = ARCHETYPE_TOP_K,
) -> list[tuple[str, float]]:
    """
    Given a normalised document embedding, return the top-k closest
    archetype categories as (category_name, cosine_score) pairs.
    """
    arch = _get_archetype_embeddings()
    if arch is None or doc_emb is None:
        return []

    scores = []
    for category, centroid in arch.items():
        sim = float(np.dot(doc_emb, centroid))
        scores.append((category, round(sim, 4)))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top_k]


# ==========================================
# CORE PARAGRAPH DETECTION
# ==========================================

def _find_core_paragraph(
    doc_emb:   np.ndarray,
    para_embs: np.ndarray,
) -> int:
    """
    Return the index of the paragraph embedding most similar to the
    document centroid (most representative paragraph).
    """
    if para_embs is None or len(para_embs) == 0:
        return 0
    sims = _cosine_sim_1d(doc_emb, para_embs)
    return int(np.argmax(sims))


# ==========================================
# PUBLIC: encode_articles
# ==========================================

def encode_articles(
    preprocessed_articles: list[dict],
    *,
    use_entity_augmented: bool = False,
) -> EncodingResult:
    """
    Run three-level SBERT encoding over a list of preprocessed articles.

    Parameters
    ----------
    preprocessed_articles : Output of preprocess_articles() — each dict
                            must contain at minimum:
                              "input_text"       (str)
                              "input_text_w_ent" (str)
                              "sentences"        (list[str])
    use_entity_augmented  : If True, prepend NER entity string to the
                            document text before encoding (slightly
                            improves entity-centred queries at the cost
                            of a small shift in the embedding space).

    Returns
    -------
    EncodingResult
        .articles         — original dicts + new SBERT fields injected
        .encodings        — parallel ArticleEncoding objects
        .doc_embeddings   — stacked (N, dim) matrix or None
        .sbert_available  — False when sentence-transformers is missing
    """
    t0    = time.time()
    model = _get_model()

    if not preprocessed_articles:
        return EncodingResult(
            articles=[],
            encodings=[],
            doc_embeddings=None,
            model_name=SBERT_MODEL,
            embedding_dim=0,
            encode_time_s=0.0,
            sbert_available=model is not None,
        )

    # Pre-warm archetype embeddings (only happens once)
    _get_archetype_embeddings()

    text_key = "input_text_w_ent" if use_entity_augmented else "input_text"
    n        = len(preprocessed_articles)

    # ────────────────────────────────────────────────────
    # LEVEL 1 — Document embeddings (batched, single pass)
    # ────────────────────────────────────────────────────
    doc_texts = [
        (a.get(text_key) or a.get("input_text") or a.get("clean_title") or "")
        for a in preprocessed_articles
    ]

    if model is not None:
        logger.info(f"SBERT: encoding {n} documents …")
        doc_embs = model.encode(
            doc_texts,
            batch_size=SBERT_BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )                                        # shape (n, dim)
        dim = doc_embs.shape[1]
    else:
        doc_embs = None
        dim      = 0

    # ────────────────────────────────────────────────────
    # LEVEL 2 & 3 — Sentence + paragraph embeddings per article
    # We batch ALL sentences from ALL articles in one call for
    # efficiency, then split back by article.
    # ────────────────────────────────────────────────────

    # Build a flat list of (article_idx, sentence_text) for batch encode
    all_sent_texts: list[str]   = []
    sent_art_idx:   list[int]   = []   # which article each sentence belongs to

    for i, art in enumerate(preprocessed_articles):
        sents = art.get("sentences", [])
        if not sents and doc_texts[i]:
            # Fallback: treat entire document as a single sentence
            sents = [doc_texts[i]]
        for s in sents:
            all_sent_texts.append(s)
            sent_art_idx.append(i)

    if model is not None and all_sent_texts:
        logger.info(
            f"SBERT: encoding {len(all_sent_texts)} sentences "
            f"across {n} articles …"
        )
        all_sent_embs = model.encode(
            all_sent_texts,
            batch_size=SBERT_BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )                                        # shape (total_sents, dim)
    else:
        all_sent_embs = None

    # ────────────────────────────────────────────────────
    # Assemble per-article ArticleEncoding objects
    # ────────────────────────────────────────────────────
    encodings: list[ArticleEncoding] = []

    # Build reverse index: article_idx → row indices in all_sent_embs
    art_sent_rows: dict[int, list[int]] = {i: [] for i in range(n)}
    if all_sent_embs is not None:
        for row, art_i in enumerate(sent_art_idx):
            art_sent_rows[art_i].append(row)

    for i, art in enumerate(preprocessed_articles):
        enc = ArticleEncoding(article_idx=i)

        # ── Document embedding ──────────────────────────
        if doc_embs is not None:
            enc.doc_embedding = doc_embs[i]

        # ── Sentence embeddings ─────────────────────────
        rows = art_sent_rows[i]
        if all_sent_embs is not None and rows:
            enc.sentence_embeddings = all_sent_embs[rows]

            # ── Paragraph embeddings (group sentences) ──
            sents = art.get("sentences", []) or [doc_texts[i]]
            paras = _group_sentences_into_paragraphs(sents)

            if len(paras) > 1:
                # Compute paragraph embeddings by mean-pooling sentence
                # embeddings within each paragraph group
                para_emb_list = []
                s_per_para    = _PARAGRAPH_GROUP_SIZE
                sent_emb_idx  = 0
                for p_idx in range(len(paras)):
                    group_rows = rows[p_idx * s_per_para:
                                      (p_idx + 1) * s_per_para]
                    if group_rows:
                        chunk = all_sent_embs[group_rows]
                        mean_vec = chunk.mean(axis=0)
                        # Re-normalise
                        norm = np.linalg.norm(mean_vec)
                        if norm > 0:
                            mean_vec = mean_vec / norm
                        para_emb_list.append(mean_vec)
                if para_emb_list:
                    enc.paragraph_embeddings = np.vstack(para_emb_list)
            else:
                # Single paragraph — same as document embedding
                enc.paragraph_embeddings = (
                    doc_embs[i:i+1] if doc_embs is not None else None
                )

        # ── Core paragraph detection ─────────────────────
        if (enc.doc_embedding is not None
                and enc.paragraph_embeddings is not None
                and len(enc.paragraph_embeddings) > 0):
            enc.core_paragraph_idx = _find_core_paragraph(
                enc.doc_embedding, enc.paragraph_embeddings
            )

        # ── Archetype matching ───────────────────────────
        if enc.doc_embedding is not None:
            enc.archetype_matches = _match_archetypes(
                enc.doc_embedding, top_k=ARCHETYPE_TOP_K
            )
            if enc.archetype_matches:
                enc.semantic_category = enc.archetype_matches[0][0]
                enc.semantic_score    = enc.archetype_matches[0][1]

        encodings.append(enc)

    # ────────────────────────────────────────────────────
    # Inject SBERT fields back into article dicts
    # ────────────────────────────────────────────────────
    enriched_articles = []
    for art, enc in zip(preprocessed_articles, encodings):
        enriched = dict(art)
        enriched.update({
            "semantic_category": enc.semantic_category,
            "semantic_score":    round(enc.semantic_score, 4),
            "archetype_matches": enc.archetype_matches,
            "core_paragraph_idx": enc.core_paragraph_idx,
            # Store embedding as plain Python list for JSON serialisation.
            # "doc_embedding" is the canonical name; "embedding" is the alias
            # consumed by event_clusterer.py (DBSCAN).
            "doc_embedding": (
                enc.doc_embedding.tolist()
                if enc.doc_embedding is not None else None
            ),
            "embedding": (
                enc.doc_embedding.tolist()
                if enc.doc_embedding is not None else None
            ),
            "sbert_encoded": enc.doc_embedding is not None,
        })
        enriched_articles.append(enriched)

    elapsed = time.time() - t0
    logger.info(
        f"SBERT encoding complete — {n} articles, "
        f"{len(all_sent_texts)} sentences, "
        f"{elapsed:.2f}s  "
        f"(model={'available' if model else 'unavailable'})"
    )

    return EncodingResult(
        articles       = enriched_articles,
        encodings      = encodings,
        doc_embeddings = doc_embs,
        model_name     = SBERT_MODEL,
        embedding_dim  = dim,
        encode_time_s  = elapsed,
        sbert_available = model is not None,
    )


# ==========================================
# PUBLIC: find_similar
# ==========================================

def find_similar(
    query_text:     str,
    result:         EncodingResult,
    top_k:          int = 5,
) -> list[dict]:
    """
    Return the top-k articles semantically most similar to query_text.

    Parameters
    ----------
    query_text  : Free-text query (e.g. "port congestion China").
    result      : EncodingResult from encode_articles().
    top_k       : Number of results to return.

    Returns
    -------
    List of article dicts (from result.articles), each with an added
    "similarity_score" float field, sorted descending by similarity.
    Returns [] if SBERT is unavailable.
    """
    model = _get_model()
    if model is None or result.doc_embeddings is None:
        logger.warning("find_similar: SBERT unavailable — returning empty.")
        return []

    query_emb = model.encode(
        [query_text],
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )[0]

    sims = _cosine_sim_1d(query_emb, result.doc_embeddings)
    top_indices = np.argsort(sims)[::-1][:top_k]

    out = []
    for idx in top_indices:
        art = dict(result.articles[idx])
        art["similarity_score"] = round(float(sims[idx]), 4)
        out.append(art)

    return out


# ==========================================
# PUBLIC: deduplicate_semantic
# ==========================================

def deduplicate_semantic(
    result:    EncodingResult,
    threshold: float = DEDUP_THRESHOLD,
) -> list[dict]:
    """
    Remove near-duplicate articles using cosine similarity of
    document embeddings.

    Algorithm (greedy, O(n²) — fast enough for n ≤ 500):
      1. Sort articles by relevance_score descending (keep the best).
      2. For each unvisited article, mark all others within `threshold`
         cosine similarity as duplicates.
      3. Return the surviving (non-duplicate) articles.

    Parameters
    ----------
    result    : EncodingResult from encode_articles().
    threshold : Cosine similarity above which two articles are
                considered near-duplicates (default 0.88).

    Returns
    -------
    Deduplicated list of article dicts, sorted by relevance_score desc.
    Includes a "dedup_kept" boolean field (always True for returned articles)
    and "dedup_similar_count" int showing how many duplicates were merged.

    Falls back to returning all articles unchanged if SBERT is unavailable.
    """
    articles   = result.articles
    doc_embs   = result.doc_embeddings

    if doc_embs is None or len(articles) == 0:
        logger.info("deduplicate_semantic: SBERT unavailable — skipping dedup.")
        return articles

    n = len(articles)

    # Sort indices by relevance_score descending to prefer higher-quality
    # articles when two near-duplicates are found.
    sorted_indices = sorted(
        range(n),
        key=lambda i: articles[i].get("relevance_score", 0),
        reverse=True,
    )

    # Pre-compute full similarity matrix in one shot
    sim_matrix = _cosine_sim_matrix(doc_embs, doc_embs)  # (n, n)

    kept      = []          # indices of surviving articles
    duplicate = [False] * n

    for idx in sorted_indices:
        if duplicate[idx]:
            continue

        # Find how many other articles this one absorbs
        similar_count = 0
        for other in sorted_indices:
            if other == idx or duplicate[other]:
                continue
            if sim_matrix[idx, other] >= threshold:
                duplicate[other] = True
                similar_count += 1

        kept.append((idx, similar_count))

    # Assemble output
    output = []
    for idx, sim_count in kept:
        art = dict(articles[idx])
        art["dedup_kept"]          = True
        art["dedup_similar_count"] = sim_count
        output.append(art)

    # Re-sort: HIGH → MEDIUM → LOW, then by score
    _level_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    output.sort(
        key=lambda a: (
            _level_order.get(a.get("impact_level", "LOW"), 2),
            -a.get("relevance_score", 0),
        )
    )

    removed = n - len(output)
    logger.info(
        f"Semantic deduplication: {n} → {len(output)} articles "
        f"({removed} near-duplicates removed, threshold={threshold})"
    )
    return output


# ==========================================
# QUICK SELF-TEST
# (python -m utils.sbert_encoder)
# ==========================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    dummy_preprocessed = [
        {
            "title":         "TSMC halts production after Taiwan earthquake",
            "input_text":    "[TITLE] TSMC halts production after Taiwan earthquake  [BODY] Taiwan Semiconductor Manufacturing Company suspended operations at its Kaohsiung plant following a 6.4 magnitude earthquake. Chip shipments to OEM partners are expected to be delayed by 3-4 weeks.",
            "input_text_w_ent": "ORG:TSMC GPE:Taiwan FAC:Kaohsiung  [TITLE] TSMC halts production after Taiwan earthquake  [BODY] Taiwan Semiconductor Manufacturing Company suspended operations at its Kaohsiung plant following a 6.4 magnitude earthquake.",
            "sentences":     [
                "Taiwan Semiconductor Manufacturing Company suspended operations at its Kaohsiung plant following a 6.4 magnitude earthquake.",
                "Chip shipments to OEM partners are expected to be delayed by 3-4 weeks.",
            ],
            "relevance_score":  85,
            "impact_level":     "HIGH",
            "matched_entities": ["TSMC"],
            "linked_nodes":     ["supplier:TSMC"],
            "source":           "FreightWaves",
            "url":              "https://example.com/tsmc",
            "published":        "2024-04-03T09:00:00Z",
        },
        {
            "title":         "TSMC suspends fab operations following earthquake near Taiwan",
            "input_text":    "[TITLE] TSMC suspends fab operations following earthquake near Taiwan  [BODY] TSMC has stopped wafer production at its southern Taiwan facility after seismic activity disrupted equipment calibration.",
            "input_text_w_ent": "ORG:TSMC GPE:Taiwan  [TITLE] TSMC suspends fab operations following earthquake near Taiwan  [BODY] TSMC has stopped wafer production at its southern Taiwan facility.",
            "sentences":     [
                "TSMC has stopped wafer production at its southern Taiwan facility after seismic activity disrupted equipment calibration.",
            ],
            "relevance_score":  78,
            "impact_level":     "HIGH",
            "matched_entities": ["TSMC"],
            "linked_nodes":     ["supplier:TSMC"],
            "source":           "Reuters",
            "url":              "https://example.com/tsmc-2",
            "published":        "2024-04-03T10:15:00Z",
        },
        {
            "title":         "Chilean lithium miners strike over wages",
            "input_text":    "[TITLE] Chilean lithium miners strike over wages  [BODY] Workers at Albemarle's Atacama operations walked out in a wage dispute. Lithium carbonate spot prices jumped 12% on supply shortage fears.",
            "input_text_w_ent": "GPE:Chile ORG:Albemarle PRODUCT:lithium  [TITLE] Chilean lithium miners strike over wages  [BODY] Workers at Albemarle's Atacama operations walked out.",
            "sentences":     [
                "Workers at Albemarle's Atacama operations walked out in a wage dispute.",
                "Lithium carbonate spot prices jumped 12% on supply shortage fears.",
            ],
            "relevance_score":  62,
            "impact_level":     "MEDIUM",
            "matched_entities": ["lithium"],
            "linked_nodes":     ["material:lithium"],
            "source":           "Mining.com",
            "url":              "https://example.com/lithium",
            "published":        "2024-04-02T14:30:00Z",
        },
    ]

    print("\n" + "═" * 65)
    print("  SBERT ENCODER SELF-TEST")
    print("═" * 65)

    result = encode_articles(dummy_preprocessed)

    if not result.sbert_available:
        print("\n⚠  sentence-transformers not installed.")
        print("   Run: pip install sentence-transformers")
        print("   Encoding skipped — all embedding fields will be None.\n")
    else:
        print(f"\nModel     : {result.model_name}  (dim={result.embedding_dim})")
        print(f"Encode    : {result.encode_time_s:.2f}s for {len(result.articles)} articles\n")

        for i, (art, enc) in enumerate(zip(result.articles, result.encodings)):
            print(f"── Article {i+1}: {art['title'][:55]}")
            print(f"   Semantic category : {art['semantic_category']}  "
                  f"(score={art['semantic_score']:.3f})")
            if art["archetype_matches"]:
                second = art["archetype_matches"][1] if len(art["archetype_matches"]) > 1 else None
                if second:
                    print(f"   2nd archetype     : {second[0]}  (score={second[1]:.3f})")
            n_sents = (enc.sentence_embeddings.shape[0]
                       if enc.sentence_embeddings is not None else 0)
            n_paras = (enc.paragraph_embeddings.shape[0]
                       if enc.paragraph_embeddings is not None else 0)
            print(f"   Sentences encoded : {n_sents}  "
                  f"| Paragraphs: {n_paras}  "
                  f"| Core para idx: {enc.core_paragraph_idx}")
            print()

        # ── Near-duplicate detection ────────────────────
        print("─" * 65)
        print("SEMANTIC DEDUPLICATION (threshold=0.88)")
        deduped = deduplicate_semantic(result, threshold=0.88)
        print(f"  Before: {len(result.articles)}  →  After: {len(deduped)}\n")
        for art in deduped:
            print(f"  ✓ {art['title'][:55]}  "
                  f"[absorbed {art.get('dedup_similar_count',0)} duplicates]")

        # ── Semantic search ─────────────────────────────
        print("\n─" * 65)
        print("SEMANTIC SEARCH: 'port disruption chip shortage Taiwan'")
        hits = find_similar("port disruption chip shortage Taiwan", result, top_k=2)
        for hit in hits:
            print(f"  sim={hit['similarity_score']:.3f}  {hit['title'][:60]}")

    print("\n" + "═" * 65 + "\n")
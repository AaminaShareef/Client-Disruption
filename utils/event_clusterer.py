"""
utils/event_clusterer.py
─────────────────────────────────────────────────────────────────────────────
DBSCAN-based supply chain event clustering.

Each article already has an SBERT embedding computed by sbert_encoder.py.
This module groups those embeddings into clusters where each cluster
represents one real-world supply chain event.

Tuning knobs
────────────
EPS          Cosine distance threshold.  Lower → tighter, more clusters.
             0.18 is a good starting point for supply-chain news.
MIN_SAMPLES  Minimum articles to form a cluster core.
             2 is almost always right for news (avoids singletons becoming
             noise when two articles cover the same event).

Noise handling
─────────────
DBSCAN labels noise points as -1.  Each noise article becomes its own
single-article "cluster" so it is never silently dropped from the pipeline.
"""

from __future__ import annotations

import logging
import numpy as np

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# DEFAULTS  (can be overridden per-call)
# ──────────────────────────────────────────────────────────────────────────────
DEFAULT_EPS         = 0.18   # cosine distance  (0 = identical, 1 = orthogonal)
DEFAULT_MIN_SAMPLES = 2


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────────────────────────────────────

def cluster_articles(
    articles:    list[dict],
    eps:         float = DEFAULT_EPS,
    min_samples: int   = DEFAULT_MIN_SAMPLES,
) -> list[dict]:
    """
    Group *articles* into event clusters using DBSCAN on their SBERT embeddings.

    Parameters
    ──────────
    articles     List of preprocessed article dicts.  Each dict must contain
                 an ``"embedding"`` key (list[float] or np.ndarray) produced
                 by sbert_encoder.py.  Articles without a valid embedding are
                 passed through as singleton clusters.
    eps          DBSCAN neighbourhood radius in cosine-distance space.
    min_samples  Minimum neighbourhood size to be considered a core point.

    Returns
    ───────
    List[dict]  One dict per cluster::

        {
          "cluster_id":    int,          # 0-indexed; noise → assigned unique id
          "is_noise":      bool,         # True for DBSCAN noise singletons
          "article_count": int,
          "articles":      List[dict],   # full article dicts
          # Cluster-level rollup fields (derived from member articles):
          "impact_level":  str,          # highest impact_level in cluster
          "risk_score":    int,          # max relevance_score in cluster
          "linked_nodes":  List[str],    # union of linked_nodes across articles
          "sources":       List[str],    # unique sources
        }
    """
    if not articles:
        return []

    # ── Partition: articles with vs without embeddings ────────────────────────
    embedded, no_embed = [], []
    for art in articles:
        emb = art.get("embedding")
        if emb is not None and len(emb) > 0:
            embedded.append(art)
        else:
            no_embed.append(art)

    if no_embed:
        logger.warning(
            f"cluster_articles: {len(no_embed)} article(s) have no embedding "
            "— treated as singletons."
        )

    clusters: list[dict] = []

    # ── DBSCAN on embedded articles ───────────────────────────────────────────
    if embedded:
        try:
            from sklearn.cluster import DBSCAN

            matrix = np.array([art["embedding"] for art in embedded], dtype=np.float32)

            # L2-normalise so cosine distance = 1 - dot(a,b)
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1.0          # guard against zero vectors
            matrix = matrix / norms

            db = DBSCAN(
                eps=eps,
                min_samples=min_samples,
                metric="cosine",
                n_jobs=-1,
            ).fit(matrix)

            labels = db.labels_             # -1 = noise

            # Group articles by cluster label
            from collections import defaultdict
            label_to_arts: dict[int, list[dict]] = defaultdict(list)
            for art, lbl in zip(embedded, labels):
                label_to_arts[lbl].append(art)

            noise_id_offset = max(label_to_arts.keys(), default=-1) + 1

            for lbl, arts in sorted(label_to_arts.items()):
                is_noise = (lbl == -1)
                if is_noise:
                    # Each noise article becomes its own singleton cluster
                    for i, art in enumerate(arts):
                        clusters.append(_make_cluster(noise_id_offset + i, art_list=[art], is_noise=True))
                    noise_id_offset += len(arts)
                else:
                    clusters.append(_make_cluster(lbl, art_list=arts, is_noise=False))

            n_real    = sum(1 for c in clusters if not c["is_noise"])
            n_noise   = sum(1 for c in clusters if     c["is_noise"])
            logger.info(
                f"DBSCAN clustering complete — "
                f"{n_real} event cluster(s), {n_noise} singleton(s) "
                f"(eps={eps}, min_samples={min_samples})"
            )

        except ImportError:
            logger.error(
                "scikit-learn not installed — falling back to per-article singletons. "
                "Run: pip install scikit-learn"
            )
            for i, art in enumerate(embedded):
                clusters.append(_make_cluster(i, art_list=[art], is_noise=True))

        except Exception as exc:
            logger.error(f"DBSCAN failed ({exc}) — falling back to per-article singletons.")
            for i, art in enumerate(embedded):
                clusters.append(_make_cluster(i, art_list=[art], is_noise=True))

    # ── Singletons for articles with no embedding ─────────────────────────────
    id_base = len(clusters)
    for i, art in enumerate(no_embed):
        clusters.append(_make_cluster(id_base + i, art_list=[art], is_noise=True))

    # Sort: real clusters first (by size desc), then singletons
    clusters.sort(key=lambda c: (c["is_noise"], -c["article_count"]))

    return clusters


def flatten_clusters(clusters: list[dict]) -> list[dict]:
    """
    Utility: given a cluster list, return all member articles in a flat list,
    with ``cluster_id`` and ``cluster_size`` injected into each article dict.
    Does NOT mutate the originals — returns shallow copies.
    """
    out = []
    for cluster in clusters:
        for art in cluster["articles"]:
            copy = dict(art)
            copy["cluster_id"]   = cluster["cluster_id"]
            copy["cluster_size"] = cluster["article_count"]
            out.append(copy)
    return out


# ──────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ──────────────────────────────────────────────────────────────────────────────

_LEVEL_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "": 0}


def _make_cluster(cluster_id: int, art_list: list[dict], is_noise: bool) -> dict:
    """Build a cluster dict from a list of articles."""
    impact_levels  = [a.get("impact_level", "LOW") for a in art_list]
    best_impact    = max(impact_levels, key=lambda l: _LEVEL_RANK.get(l, 0))
    max_score      = max((a.get("relevance_score", 0) for a in art_list), default=0)

    linked_nodes: list[str] = []
    seen_nodes: set[str]    = set()
    for art in art_list:
        for node in art.get("linked_nodes", []):
            if node not in seen_nodes:
                linked_nodes.append(node)
                seen_nodes.add(node)

    sources = list({a.get("source", "") for a in art_list if a.get("source")})

    return {
        "cluster_id":    cluster_id,
        "is_noise":      is_noise,
        "article_count": len(art_list),
        "articles":      art_list,
        "impact_level":  best_impact,
        "risk_score":    max_score,
        "linked_nodes":  linked_nodes,
        "sources":       sources,
    }
"""
utils/cross_cluster_dedup.py
─────────────────────────────────────────────────────────────────────────────
Cross-cluster deduplication for the Supply Chain Disruption Intelligence System.

As described in §6.1 of the documentation:

  "If Cluster 0 (today) and Cluster 7 (from 2 days ago) are both about the
   same tariff announcement, the system detects their cluster centroids are
   within cosine distance 0.12 and merges them, promoting new unique points
   from Cluster 0 into the existing Cluster 7 record."

This module handles two use cases:

  1. Within-run deduplication:
     Remove clusters that are semantically very similar to each other within
     the current analysis run.

  2. Cross-run deduplication (incremental):
     Given a new run's clusters and a set of historical cluster records
     (loaded from past JSONL/JSON run files), detect which new clusters
     describe events already seen in earlier runs.

Public API
──────────
  deduplicate_clusters_within_run(clusters, threshold)
      Remove near-duplicate clusters within a single run.
      Returns pruned cluster list.

  find_cross_run_duplicates(new_clusters, historical_clusters, threshold)
      Identify which new clusters match historical ones.
      Returns list of (new_idx, hist_idx, cosine_similarity) tuples.

  merge_intelligence_points(existing_cluster, new_cluster)
      Promote unique MMR sentences from new_cluster into existing_cluster.
      Returns updated existing_cluster.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# DEFAULTS
# ──────────────────────────────────────────────────────────────────────────────
WITHIN_RUN_THRESHOLD  = 0.20   # cosine distance below which clusters are near-duplicates
CROSS_RUN_THRESHOLD   = 0.15   # tighter threshold for cross-run same-event detection


# ──────────────────────────────────────────────────────────────────────────────
# CLUSTER CENTROID HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _cluster_centroid(cluster: dict) -> Optional[np.ndarray]:
    """
    Compute the centroid of a cluster from its member article embeddings.
    Returns None if no embeddings are available.
    """
    articles = cluster.get("articles", [])
    embs = []
    for art in articles:
        emb = art.get("doc_embedding") or art.get("embedding")
        if emb is not None:
            try:
                v = np.array(emb, dtype=np.float32)
                norm = np.linalg.norm(v)
                if norm > 0:
                    embs.append(v / norm)
            except Exception:
                pass

    if not embs:
        return None

    centroid = np.mean(embs, axis=0)
    norm     = np.linalg.norm(centroid)
    if norm > 0:
        centroid /= norm
    return centroid


def _cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance in [0, 1] from two unit vectors."""
    return float(1.0 - np.dot(a, b))


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC: WITHIN-RUN CLUSTER DEDUPLICATION
# ──────────────────────────────────────────────────────────────────────────────

def deduplicate_clusters_within_run(
    clusters:  list[dict],
    threshold: float = WITHIN_RUN_THRESHOLD,
) -> list[dict]:
    """
    Remove near-duplicate clusters within a single analysis run.

    Algorithm (greedy, sort by size desc → prefer larger clusters):
      For each cluster (largest first), mark all subsequent clusters
      whose centroid is within `threshold` cosine distance as duplicates.
      Duplicate clusters' articles are merged into the surviving cluster.

    Parameters
    ──────────
    clusters   Cluster list from event_clusterer (after attach_summaries,
               attach_briefs, attach_topics, enrich_clusters_with_risk).
    threshold  Cosine distance below which two clusters describe the same event.

    Returns
    ───────
    Pruned list with near-duplicate clusters merged into the larger cluster.
    Noise singletons (is_noise=True) are never merged and pass through unchanged.
    """
    # Separate real clusters from noise singletons
    real    = [c for c in clusters if not c.get("is_noise", False)]
    noise   = [c for c in clusters if c.get("is_noise", False)]

    if len(real) <= 1:
        return clusters

    # Pre-compute centroids
    centroids = [_cluster_centroid(c) for c in real]

    # Sort by article_count desc (prefer keeping larger clusters)
    order = sorted(range(len(real)), key=lambda i: -real[i].get("article_count", 0))

    merged    = [False] * len(real)
    surviving = []

    for i in order:
        if merged[i]:
            continue
        ci = centroids[i]
        if ci is None:
            surviving.append(real[i])
            continue

        # Find all unmerged clusters within threshold
        absorb_idx = []
        for j in order:
            if j == i or merged[j]:
                continue
            cj = centroids[j]
            if cj is None:
                continue
            dist = _cosine_distance(ci, cj)
            if dist <= threshold:
                absorb_idx.append(j)

        if absorb_idx:
            # Merge articles from near-duplicates into cluster i
            base = real[i]
            for j in absorb_idx:
                merged[j] = True
                for art in real[j].get("articles", []):
                    base["articles"].append(art)
                base["article_count"] = len(base["articles"])
                # Union sources
                for src in real[j].get("sources", []):
                    if src not in base["sources"]:
                        base["sources"].append(src)
                # Union linked_nodes
                existing_nodes = set(base.get("linked_nodes", []))
                for node in real[j].get("linked_nodes", []):
                    if node not in existing_nodes:
                        base["linked_nodes"].append(node)
                        existing_nodes.add(node)
            logger.info(
                f"Merged {len(absorb_idx)} near-duplicate cluster(s) into "
                f"cluster {base.get('cluster_id')} "
                f"(threshold={threshold})"
            )

        surviving.append(real[i])

    # Sort surviving: real by risk/size, then noise
    surviving.sort(key=lambda c: (
        -c.get("composite_risk_score", c.get("risk_score", 0)),
        -c.get("article_count", 0),
    ))

    merged_count = len(real) - len(surviving)
    if merged_count:
        logger.info(
            f"Within-run cluster dedup: {len(real)} → {len(surviving)} clusters "
            f"({merged_count} merged)"
        )

    return surviving + noise


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC: CROSS-RUN DUPLICATE DETECTION
# ──────────────────────────────────────────────────────────────────────────────

def find_cross_run_duplicates(
    new_clusters:  list[dict],
    hist_clusters: list[dict],
    threshold:     float = CROSS_RUN_THRESHOLD,
) -> list[tuple[int, int, float]]:
    """
    Identify new clusters that describe events already seen in historical runs.

    Parameters
    ──────────
    new_clusters   Clusters from the current analysis run.
    hist_clusters  Clusters loaded from previous run JSON files.
    threshold      Cosine distance below which an event is considered already seen.

    Returns
    ───────
    List of (new_idx, hist_idx, cosine_distance) tuples for matched pairs,
    sorted by cosine_distance ascending (closest match first).
    """
    new_centroids  = [_cluster_centroid(c) for c in new_clusters]
    hist_centroids = [_cluster_centroid(c) for c in hist_clusters]

    matches = []
    for ni, nc in enumerate(new_centroids):
        if nc is None:
            continue
        for hi, hc in enumerate(hist_centroids):
            if hc is None:
                continue
            dist = _cosine_distance(nc, hc)
            if dist <= threshold:
                matches.append((ni, hi, round(dist, 4)))

    matches.sort(key=lambda x: x[2])

    if matches:
        logger.info(
            f"Cross-run dedup: {len(matches)} new cluster(s) match historical events "
            f"(threshold={threshold})"
        )

    return matches


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC: INTELLIGENCE POINT PROMOTION
# ──────────────────────────────────────────────────────────────────────────────

def merge_intelligence_points(
    existing_cluster: dict,
    new_cluster: dict,
    dedup_threshold: float = 0.88,
) -> dict:
    """
    Promote unique MMR sentences from new_cluster into existing_cluster,
    deduplicating by cosine similarity.

    Used when cross-run matching confirms a new cluster is about the same
    event as a historical cluster — we keep the historical record as the
    canonical entry but enrich it with any new facts discovered.

    Parameters
    ──────────
    existing_cluster  Historical cluster record (will be mutated).
    new_cluster       Current run cluster with potentially new information.
    dedup_threshold   Cosine similarity above which a sentence is considered
                      already present in existing_cluster.

    Returns
    ───────
    Updated existing_cluster with promoted unique sentences.
    """
    existing_mmr = existing_cluster.get("mmr_sentences", [])
    new_mmr      = new_cluster.get("mmr_sentences", [])

    if not new_mmr:
        return existing_cluster

    # Try embedding-based dedup; fall back to string-based
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        all_sents = existing_mmr + new_mmr
        embs = model.encode(
            all_sents,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        existing_embs = embs[:len(existing_mmr)]
        new_embs      = embs[len(existing_mmr):]

        promoted_sents = []
        promoted_embs  = list(existing_embs) if len(existing_mmr) > 0 else []

        for i, (sent, emb) in enumerate(zip(new_mmr, new_embs)):
            if not promoted_embs:
                promoted_sents.append(sent)
                promoted_embs.append(emb)
                continue
            sims = [float(import_np().dot(emb, pe)) for pe in promoted_embs]
            if max(sims) < dedup_threshold:
                promoted_sents.append(sent)
                promoted_embs.append(emb)

        if promoted_sents:
            existing_cluster["mmr_sentences"] = existing_mmr + promoted_sents
            logger.info(
                f"Intelligence promotion: {len(promoted_sents)} new unique "
                f"sentence(s) added to cluster {existing_cluster.get('cluster_id')}"
            )

    except Exception:
        # String-based fallback
        existing_lower = {s.lower()[:80] for s in existing_mmr}
        promoted = [s for s in new_mmr if s.lower()[:80] not in existing_lower]
        if promoted:
            existing_cluster["mmr_sentences"] = existing_mmr + promoted
            logger.info(
                f"Intelligence promotion (string): {len(promoted)} new sentence(s) "
                f"promoted to cluster {existing_cluster.get('cluster_id')}"
            )

    return existing_cluster


def import_np():
    import numpy as np
    return np
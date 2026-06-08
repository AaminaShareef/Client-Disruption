"""
utils/summariser.py
─────────────────────────────────────────────────────────────────────────────
Extractive summarisation using LexRank (sentence-graph + stationary
distribution).

Two entry points
────────────────
summarise_cluster(cluster)   → 3-4 sentence brief for one event cluster
summarise_article(article)   → 2-3 sentence brief for a single article

Both fall back gracefully:
  • If SBERT sentence embeddings are not available, cosine similarity is
    computed from TF-IDF vectors (zero extra dependencies).
  • If an article has no usable sentences, its clean_title is returned.

LexRank reference
─────────────────
Erkan & Radev, "LexRank: Graph-based Lexical Centrality as Salience in Text
Summarization", JAIR 2004.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────
DEFAULT_CLUSTER_SENTENCES  = 4   # max sentences in a cluster brief
DEFAULT_ARTICLE_SENTENCES  = 2   # max sentences in a per-article brief
LEXRANK_THRESHOLD          = 0.1 # cosine similarity below this → no edge
LEXRANK_DAMPING            = 0.85
LEXRANK_MAX_ITER           = 100
LEXRANK_TOLERANCE          = 1e-5
MIN_SENTENCE_TOKENS        = 6   # filter out very short / garbled sentences
MAX_SENTENCE_CHARS         = 320 # truncate runaway sentences


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────────────────────────────────────

def summarise_cluster(cluster: dict, n: int = DEFAULT_CLUSTER_SENTENCES) -> str:
    """
    Produce an extractive summary for *cluster* (output of event_clusterer).

    Strategy
    ────────
    1. Collect all sentences from every article in the cluster.
    2. Score them with LexRank.
    3. Pick the top-n by score, then re-order them chronologically (by article
       position) so the brief reads naturally.
    """
    articles = cluster.get("articles", [])
    if not articles:
        return ""

    all_sentences: list[tuple[str, list[float] | None]] = []   # (text, embedding|None)
    for art in articles:
        sents  = art.get("sentences", [])
        embeds = art.get("sentence_embeddings")  # may be absent
        for i, sent in enumerate(sents):
            text = _clean_sentence(sent)
            if not _is_usable(text):
                continue
            emb = embeds[i] if (embeds and i < len(embeds)) else None
            all_sentences.append((text, emb))

    if not all_sentences:
        # Fallback: join titles
        titles = [a.get("clean_title", "") for a in articles if a.get("clean_title")]
        return "  ".join(titles[:n]) if titles else ""

    return _lexrank_summary(all_sentences, n)


def summarise_article(article: dict, n: int = DEFAULT_ARTICLE_SENTENCES) -> str:
    """
    Produce a short extractive summary for a single *article*.
    Uses ``article["sentences"]`` and optionally ``article["sentence_embeddings"]``.
    """
    sents  = article.get("sentences", [])
    embeds = article.get("sentence_embeddings")

    pairs: list[tuple[str, list[float] | None]] = []
    for i, sent in enumerate(sents):
        text = _clean_sentence(sent)
        if not _is_usable(text):
            continue
        emb = embeds[i] if (embeds and i < len(embeds)) else None
        pairs.append((text, emb))

    if not pairs:
        return article.get("clean_title", "")

    return _lexrank_summary(pairs, n)


def attach_summaries(
    clusters: list[dict],
    per_article: bool = False,
) -> list[dict]:
    """
    Convenience function: enrich each cluster dict with a ``"summary"`` field.
    If *per_article* is True, also add ``"summary"`` to every article dict.
    Returns the same list (mutated in-place).
    """
    for cluster in clusters:
        cluster["summary"] = summarise_cluster(cluster)
        if per_article:
            for art in cluster.get("articles", []):
                art["summary"] = summarise_article(art)
    return clusters


# ──────────────────────────────────────────────────────────────────────────────
# LEXRANK CORE
# ──────────────────────────────────────────────────────────────────────────────

def _lexrank_summary(
    sent_pairs: list[tuple[str, Optional[list[float]]]],
    n: int,
) -> str:
    """
    Run LexRank on *sent_pairs* and return the top-*n* sentences joined by spaces.
    """
    texts = [p[0] for p in sent_pairs]
    embeds = [p[1] for p in sent_pairs]

    # ── Build similarity matrix ───────────────────────────────────────────────
    use_sbert = all(e is not None for e in embeds)

    if use_sbert:
        sim_matrix = _cosine_matrix_from_embeddings(
            [np.array(e, dtype=np.float32) for e in embeds]
        )
    else:
        sim_matrix = _cosine_matrix_from_tfidf(texts)

    n_sents = len(texts)
    if n_sents == 1:
        return texts[0]

    # ── Threshold → adjacency ────────────────────────────────────────────────
    adj = (sim_matrix >= LEXRANK_THRESHOLD).astype(np.float32)
    np.fill_diagonal(adj, 0.0)

    # ── Power-iteration (degree-normalised + damping) ────────────────────────
    degree = adj.sum(axis=1)
    degree[degree == 0] = 1.0       # guard isolated nodes
    trans  = (adj / degree[:, None]).T

    scores = np.ones(n_sents, dtype=np.float32) / n_sents
    for _ in range(LEXRANK_MAX_ITER):
        new_scores = (1 - LEXRANK_DAMPING) / n_sents + LEXRANK_DAMPING * (trans @ scores)
        if np.abs(new_scores - scores).max() < LEXRANK_TOLERANCE:
            scores = new_scores
            break
        scores = new_scores

    # ── Pick top-n, preserve original order ──────────────────────────────────
    actual_n   = min(n, n_sents)
    top_idx    = sorted(np.argsort(scores)[-actual_n:].tolist())   # chronological
    summary    = "  ".join(texts[i] for i in top_idx)
    return summary


# ──────────────────────────────────────────────────────────────────────────────
# SIMILARITY UTILITIES
# ──────────────────────────────────────────────────────────────────────────────

def _cosine_matrix_from_embeddings(vecs: list[np.ndarray]) -> np.ndarray:
    matrix = np.stack(vecs)                             # (n, d)
    norms  = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    matrix = matrix / norms
    return matrix @ matrix.T                            # (n, n)  cosine sim


def _cosine_matrix_from_tfidf(texts: list[str]) -> np.ndarray:
    """Lightweight TF-IDF cosine similarity — no sklearn required."""
    vocab: dict[str, int] = {}
    token_lists: list[list[str]] = []
    for text in texts:
        tokens = re.findall(r"[a-z]{3,}", text.lower())
        token_lists.append(tokens)
        for tok in tokens:
            if tok not in vocab:
                vocab[tok] = len(vocab)

    n, v = len(texts), len(vocab)
    if v == 0:
        return np.eye(n, dtype=np.float32)

    # TF
    tf = np.zeros((n, v), dtype=np.float32)
    for i, tokens in enumerate(token_lists):
        count = Counter(tokens)
        total = sum(count.values()) or 1
        for tok, c in count.items():
            tf[i, vocab[tok]] = c / total

    # IDF
    df   = (tf > 0).sum(axis=0).astype(np.float32)
    idf  = np.log((n + 1) / (df + 1)) + 1.0
    tfidf = tf * idf

    norms = np.linalg.norm(tfidf, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    tfidf = tfidf / norms
    return tfidf @ tfidf.T


# ──────────────────────────────────────────────────────────────────────────────
# SENTENCE HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _clean_sentence(sent: str) -> str:
    sent = sent.strip()
    if len(sent) > MAX_SENTENCE_CHARS:
        sent = sent[:MAX_SENTENCE_CHARS].rsplit(" ", 1)[0] + "…"
    return sent


def _is_usable(sent: str) -> bool:
    tokens = sent.split()
    if len(tokens) < MIN_SENTENCE_TOKENS:
        return False
    # Skip sentences that look like boilerplate / dates / single-line headers
    if re.fullmatch(r"[\d\W]+", sent):
        return False
    return True
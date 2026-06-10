"""
utils/topic_modeller.py
─────────────────────────────────────────────────────────────────────────────
BERTopic-based thematic topic modelling for supply chain event clusters.

Purpose
───────
DBSCAN clusters articles into events (same incident, multiple sources).
BERTopic operates one level higher — it groups those events into themes
(e.g. "Lithium supply shortage", "Port congestion Asia", "Labour disputes").

This gives the dashboard a second view: instead of 30 individual event
cards, the analyst sees 5–8 named themes with the events underneath.

Architecture
────────────
• Uses SBERT doc_embeddings already computed by sbert_encoder.py.
  No second encoding pass needed.
• BERTopic runs c-TF-IDF over article titles/summaries to name topics.
• Falls back to keyword-based TF-IDF clustering if bertopic is not
  installed (zero extra dependencies for the fallback path).

Config (.env)
─────────────
  BERTOPIC_MIN_TOPIC_SIZE   int   Min articles per topic.  Default 3.
  BERTOPIC_NR_TOPICS        int   Target topic count.  Default "auto".
                                  Set to an int (e.g. 8) to force reduction.

Public API
──────────
  model_topics(articles)  →  TopicResult

  TopicResult:
    .topics        list[TopicInfo]   — each named theme
    .article_map   dict[str, int]    — article url → topic_id (-1 = outlier)
    .topic_count   int
    .outlier_count int

  TopicInfo:
    .topic_id      int
    .label         str               — auto-generated name (e.g. "lithium mine Chile")
    .keywords      list[str]         — top representative words
    .article_count int
    .impact_level  str               — highest impact in topic
    .risk_score    int               — max relevance_score in topic

  attach_topics(clusters, topic_result)
      Injects topic_id and topic_label into each cluster dict.
      Returns the same list (mutated in-place).
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────

_MIN_TOPIC_SIZE = int(os.getenv("BERTOPIC_MIN_TOPIC_SIZE", "3"))
_NR_TOPICS_ENV  = os.getenv("BERTOPIC_NR_TOPICS", "auto")
_NR_TOPICS      = None if _NR_TOPICS_ENV == "auto" else int(_NR_TOPICS_ENV)

# ──────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TopicInfo:
    topic_id:      int
    label:         str
    keywords:      list[str]
    article_count: int
    impact_level:  str  = "LOW"
    risk_score:    int  = 0


@dataclass
class TopicResult:
    topics:        list[TopicInfo]
    article_map:   dict[str, int]   # url → topic_id
    topic_count:   int
    outlier_count: int


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

_LEVEL_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "": 0}

_STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "has", "have", "had", "will", "would", "could", "should",
    "that", "this", "it", "its", "they", "their", "them", "he", "she",
    "his", "her", "we", "our", "you", "your", "can", "may", "might",
    "not", "no", "new", "report", "said", "says", "say", "also",
    "after", "over", "more", "about", "up", "out", "into",
    "amid", "due", "amid", "amid", "per", "vs",
}


def _doc_text(article: dict) -> str:
    """Combine title + summary for keyword extraction."""
    title   = article.get("clean_title") or article.get("title", "")
    summary = article.get("clean_body")  or article.get("summary", "") or ""
    return (title + " " + summary[:300]).lower()


def _top_keywords(texts: list[str], n: int = 5) -> list[str]:
    """
    Lightweight c-TF-IDF keyword extraction (no sklearn required).
    Returns the top-n class-distinctive terms.
    """
    from collections import Counter

    # Tokenise
    tokens_per_doc = [re.findall(r"[a-z]{4,}", t) for t in texts]

    # TF per class (all docs in one pseudo-document)
    class_tokens = [t for tokens in tokens_per_doc for t in tokens
                    if t not in _STOP_WORDS]
    tf = Counter(class_tokens)

    # IDF proxy: how rare is each term across individual docs?
    doc_freq: Counter = Counter()
    for tokens in tokens_per_doc:
        for tok in set(tokens):
            if tok not in _STOP_WORDS:
                doc_freq[tok] += 1

    n_docs = max(len(texts), 1)
    scores: dict[str, float] = {}
    for tok, freq in tf.items():
        idf = np.log(n_docs / (doc_freq.get(tok, 1)))
        scores[tok] = freq * idf

    top = sorted(scores, key=lambda k: -scores[k])[:n]
    return top


def _build_topic_label(keywords: list[str]) -> str:
    """Turn top keywords into a readable 3-word label."""
    return " ".join(keywords[:3]).title() if keywords else "General News"


# ──────────────────────────────────────────────────────────────────────────────
# BERTOPIC PATH
# ──────────────────────────────────────────────────────────────────────────────

def _run_bertopic(
    articles:   list[dict],
    embeddings: np.ndarray,
) -> Optional[TopicResult]:
    """
    Run BERTopic with pre-computed SBERT embeddings.
    Returns None if bertopic is not installed.
    """
    try:
        from bertopic import BERTopic
        from bertopic.representation import KeyBERTInspired
        from sklearn.feature_extraction.text import CountVectorizer
    except ImportError:
        return None

    docs = [_doc_text(a) for a in articles]

    vectorizer = CountVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        min_df=2,
        max_features=5000,
    )
    representation = KeyBERTInspired()

    topic_model = BERTopic(
        embedding_model=None,          # embeddings already computed
        vectorizer_model=vectorizer,
        representation_model=representation,
        min_topic_size=_MIN_TOPIC_SIZE,
        nr_topics=_NR_TOPICS,
        calculate_probabilities=False,
        verbose=False,
    )

    try:
        topics_raw, _ = topic_model.fit_transform(docs, embeddings)
    except Exception as e:
        logger.warning(f"BERTopic fit_transform failed: {e}")
        return None

    # ── Build TopicInfo list ──────────────────────────────
    topic_infos: dict[int, TopicInfo] = {}
    article_map: dict[str, int] = {}

    for art, tid in zip(articles, topics_raw):
        url = art.get("url", "")
        article_map[url] = int(tid)

        if tid == -1:
            continue  # outlier

        if tid not in topic_infos:
            # Get BERTopic keywords for this topic
            try:
                kw_scores = topic_model.get_topic(tid) or []
                keywords  = [w for w, _ in kw_scores[:6]]
            except Exception:
                keywords = []
            label = _build_topic_label(keywords)
            topic_infos[tid] = TopicInfo(
                topic_id=tid, label=label, keywords=keywords,
                article_count=0, impact_level="LOW", risk_score=0,
            )

        ti = topic_infos[tid]
        ti.article_count += 1

        level = art.get("impact_level", "LOW")
        if _LEVEL_RANK.get(level, 0) > _LEVEL_RANK.get(ti.impact_level, 0):
            ti.impact_level = level
        score = art.get("relevance_score", 0)
        if score > ti.risk_score:
            ti.risk_score = score

    topics = sorted(topic_infos.values(), key=lambda t: -t.article_count)
    outlier_count = sum(1 for tid in topics_raw if tid == -1)

    logger.info(
        f"BERTopic: {len(topics)} topic(s), "
        f"{outlier_count} outlier(s) from {len(articles)} articles"
    )
    return TopicResult(
        topics=topics,
        article_map=article_map,
        topic_count=len(topics),
        outlier_count=outlier_count,
    )


# ──────────────────────────────────────────────────────────────────────────────
# FALLBACK: TF-IDF KMEANS PATH
# ──────────────────────────────────────────────────────────────────────────────

def _run_tfidf_fallback(
    articles:   list[dict],
    embeddings: np.ndarray,
    n_topics:   int = 8,
) -> TopicResult:
    """
    Pure-numpy fallback using cosine k-means on SBERT embeddings.
    No sklearn or bertopic required.
    """
    n = len(articles)
    n_topics = min(n_topics, max(1, n // _MIN_TOPIC_SIZE))

    # Normalise embeddings
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    emb_norm = embeddings / norms

    # K-means (cosine = 1 - dot after L2 norm)
    rng = np.random.default_rng(42)
    centers = emb_norm[rng.choice(n, size=n_topics, replace=False)]

    labels = np.zeros(n, dtype=int)
    for _ in range(30):
        sims   = emb_norm @ centers.T          # (n, k)
        new_labels = np.argmax(sims, axis=1)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for k in range(n_topics):
            mask = labels == k
            if mask.any():
                centers[k] = emb_norm[mask].mean(axis=0)
                c_norm = np.linalg.norm(centers[k])
                if c_norm > 0:
                    centers[k] /= c_norm

    # ── Build TopicInfo list ──────────────────────────────
    topic_infos: dict[int, TopicInfo] = {}
    article_map: dict[str, int]       = {}
    topic_texts: dict[int, list[str]] = {}

    for art, tid in zip(articles, labels):
        tid = int(tid)
        url = art.get("url", "")
        article_map[url] = tid

        if tid not in topic_infos:
            topic_infos[tid] = TopicInfo(
                topic_id=tid, label="", keywords=[],
                article_count=0, impact_level="LOW", risk_score=0,
            )
            topic_texts[tid] = []

        ti = topic_infos[tid]
        ti.article_count += 1
        topic_texts[tid].append(_doc_text(art))

        level = art.get("impact_level", "LOW")
        if _LEVEL_RANK.get(level, 0) > _LEVEL_RANK.get(ti.impact_level, 0):
            ti.impact_level = level
        score = art.get("relevance_score", 0)
        if score > ti.risk_score:
            ti.risk_score = score

    for tid, ti in topic_infos.items():
        keywords     = _top_keywords(topic_texts[tid])
        ti.keywords  = keywords
        ti.label     = _build_topic_label(keywords)

    topics = sorted(topic_infos.values(), key=lambda t: -t.article_count)

    logger.info(
        f"TF-IDF fallback topics: {len(topics)} from {len(articles)} articles"
    )
    return TopicResult(
        topics=topics,
        article_map=article_map,
        topic_count=len(topics),
        outlier_count=0,
    )


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────────────────────────────────────

def model_topics(articles: list[dict]) -> Optional[TopicResult]:
    """
    Run topic modelling over a list of articles.

    Uses pre-computed ``doc_embedding`` or ``embedding`` fields.
    If fewer than MIN_TOPIC_SIZE * 2 articles have embeddings,
    returns None (not enough data to model).

    Tries BERTopic first; falls back to TF-IDF k-means if not installed.

    Parameters
    ──────────
    articles   List of article dicts enriched by sbert_encoder.

    Returns
    ───────
    TopicResult  or  None if insufficient data.
    """
    # ── Collect embeddings ────────────────────────────────
    embedded_arts: list[dict]        = []
    emb_list:      list[list[float]] = []

    for art in articles:
        emb = art.get("doc_embedding") or art.get("embedding")
        if emb is not None and len(emb) > 0:
            embedded_arts.append(art)
            emb_list.append(emb)

    min_needed = _MIN_TOPIC_SIZE * 2
    if len(embedded_arts) < min_needed:
        logger.info(
            f"topic_modeller: only {len(embedded_arts)} embedded articles "
            f"(need ≥ {min_needed}) — skipping."
        )
        return None

    embeddings = np.array(emb_list, dtype=np.float32)

    # ── Try BERTopic, fall back to TF-IDF ─────────────────
    result = _run_bertopic(embedded_arts, embeddings)
    if result is None:
        logger.info("BERTopic not available — using TF-IDF k-means fallback.")
        result = _run_tfidf_fallback(embedded_arts, embeddings)

    return result


def attach_topics(
    clusters:     list[dict],
    topic_result: Optional[TopicResult],
) -> list[dict]:
    """
    Inject ``topic_id`` and ``topic_label`` into each cluster dict,
    derived from the topic assignments of their member articles.

    A cluster's topic = the plurality topic among its member articles.
    Mutates and returns the same list.
    """
    if topic_result is None:
        for c in clusters:
            c["topic_id"]    = -1
            c["topic_label"] = "Uncategorised"
        return clusters

    # Build a label lookup
    label_map = {t.topic_id: t.label for t in topic_result.topics}

    for cluster in clusters:
        votes: dict[int, int] = {}
        for art in cluster.get("articles", []):
            url = art.get("url", "")
            tid = topic_result.article_map.get(url, -1)
            votes[tid] = votes.get(tid, 0) + 1

        # Plurality vote; -1 (outlier) loses ties
        best_tid = max(votes, key=lambda t: (t != -1, votes[t]))
        cluster["topic_id"]    = int(best_tid)
        cluster["topic_label"] = label_map.get(best_tid, "General News")

    return clusters


def topics_to_dict(topic_result: TopicResult) -> list[dict]:
    """Serialise TopicResult.topics to a JSON-safe list for the API response."""
    return [
        {
            "topic_id":      t.topic_id,
            "label":         t.label,
            "keywords":      t.keywords,
            "article_count": t.article_count,
            "impact_level":  t.impact_level,
            "risk_score":    t.risk_score,
        }
        for t in topic_result.topics
    ]
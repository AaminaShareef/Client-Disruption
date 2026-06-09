"""
utils/topic_modeller.py
─────────────────────────────────────────────────────────────────────────────
Lightweight BERTopic-inspired topic modelling for the Supply Chain
Disruption Intelligence System.

Architecture
────────────
This module approximates the BERTopic pipeline described in the system
documentation using only dependencies already present in the stack
(numpy, scikit-learn) plus the optional bertopic package when available.

Two-level topic hierarchy (as per documentation §7.2)
──────────────────────────────────────────────────────
  Level 1: Disruption Domain  (Geopolitical, Natural Disaster, Labor, etc.)
  Level 2: Affected Industries (derived from term co-occurrence)

When BERTopic is installed (pip install bertopic):
  Full pipeline:  SBERT embeddings → UMAP → HDBSCAN → c-TF-IDF labelling

When BERTopic is NOT installed (graceful fallback):
  Cosine similarity to hard-coded domain centroid sentences → soft-label
  each cluster to the closest domain using SBERT archetypes.

Public API
──────────
  model_topics(clusters, articles)
      Assign topic labels to both articles and clusters.
      Returns TopicResult namedtuple.

  build_cross_industry_map(topic_result)
      Compute cross-industry co-occurrence chains (§7.4).
      Returns {source_industry: [(target_industry, confidence, count), ...]}

  attach_topics(clusters, articles)
      Convenience wrapper — mutates clusters and articles in-place.
      Returns TopicResult.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# DISRUPTION DOMAIN DEFINITIONS (Level 1)
# ──────────────────────────────────────────────────────────────────────────────

DISRUPTION_DOMAINS: dict[str, dict] = {
    "geopolitical": {
        "label":       "Geopolitical / Trade Policy",
        "keywords":    ["tariff", "sanction", "embargo", "trade war", "export ban",
                        "restriction", "levy", "duty", "geopolit", "conflict",
                        "war", "tension", "ban", "blockade", "political"],
        "industries":  ["Metals", "Energy", "Agriculture", "Semiconductors"],
        "archetypes":  [
            "New export restrictions were imposed on semiconductor materials.",
            "Trade war tariffs have sharply increased the cost of imported raw materials.",
            "Sanctions prevent the company from sourcing components from the supplier.",
            "The government banned exports of critical minerals amid escalating tensions.",
        ],
    },
    "natural_disaster": {
        "label":       "Natural Disaster & Climate",
        "keywords":    ["flood", "earthquake", "typhoon", "hurricane", "tsunami",
                        "wildfire", "drought", "storm", "cyclone", "disaster",
                        "rainfall", "climate", "inundated", "seismic", "evacuate"],
        "industries":  ["Mining", "Agriculture", "Logistics", "Energy"],
        "archetypes":  [
            "A major earthquake struck the manufacturing region causing structural damage.",
            "Severe flooding has inundated the industrial zone and halted logistics.",
            "The typhoon destroyed warehouses and disrupted port access roads.",
            "Wildfires forced the evacuation of workers and closure of the facility.",
        ],
    },
    "labor": {
        "label":       "Labor & Industrial Action",
        "keywords":    ["strike", "walkout", "union", "labor", "labour", "worker",
                        "wage", "protest", "picket", "dispute", "industrial action",
                        "dock", "dockworker", "longshoreman", "slowdown"],
        "industries":  ["Logistics", "Automotive", "Energy", "Mining"],
        "archetypes":  [
            "Workers walked off the job in a strike over wage disputes.",
            "The union called a nationwide walkout disrupting logistics operations.",
            "Labour unrest at the facility has stopped production for three days.",
            "Dockworkers refused to unload vessels amid contract negotiations.",
        ],
    },
    "infrastructure": {
        "label":       "Infrastructure Failure",
        "keywords":    ["port closure", "canal", "blocked", "grounded", "collision",
                        "bridge", "rail", "infrastructure", "breakdown", "failure",
                        "outage", "congestion", "chokepoint", "bottleneck"],
        "industries":  ["Logistics", "Shipping", "Manufacturing"],
        "archetypes":  [
            "The container ship ran aground blocking the canal for several days.",
            "Port operations suspended after crane malfunction caused terminal congestion.",
            "Rail network outage disrupted overland freight across the region.",
        ],
    },
    "regulatory": {
        "label":       "Regulatory & Policy",
        "keywords":    ["regulation", "compliance", "policy", "ban", "recall",
                        "cbam", "carbon", "emission", "standard", "rule",
                        "inspection", "license", "permit", "authority", "epa"],
        "industries":  ["Pharmaceuticals", "Chemicals", "Agriculture", "Automotive"],
        "archetypes":  [
            "New EU carbon border adjustment mechanism regulations came into force.",
            "Regulators issued a product recall affecting millions of units globally.",
            "The government imposed new environmental compliance requirements on factories.",
        ],
    },
    "financial": {
        "label":       "Financial Shock",
        "keywords":    ["currency", "exchange rate", "inflation", "interest rate",
                        "credit", "default", "bankruptcy", "financial", "cost surge",
                        "price spike", "futures", "commodity price", "usd", "yuan"],
        "industries":  ["All commodity-intensive sectors"],
        "archetypes":  [
            "Rapid USD appreciation against emerging market currencies raised import costs.",
            "Commodity price surge driven by speculative pressure and supply fears.",
            "The supplier filed for bankruptcy protection citing raw material cost increases.",
        ],
    },
    "pandemic_health": {
        "label":       "Pandemic & Health",
        "keywords":    ["covid", "pandemic", "lockdown", "quarantine", "outbreak",
                        "health", "disease", "virus", "shutdown", "closure",
                        "workforce", "absenteeism"],
        "industries":  ["Pharmaceuticals", "Food", "Electronics", "Logistics"],
        "archetypes":  [
            "Factory shutdowns in manufacturing hubs due to pandemic lockdown measures.",
            "Workforce quarantine requirements reduced production capacity significantly.",
        ],
    },
    "cyber_technology": {
        "label":       "Cyber & Technology",
        "keywords":    ["cyberattack", "ransomware", "hack", "breach", "outage",
                        "it failure", "system failure", "cyber", "malware",
                        "disruption", "technology", "semiconductor shortage", "chip shortage"],
        "industries":  ["Semiconductors", "Automotive", "Finance"],
        "archetypes":  [
            "TSMC production was halted following a sophisticated cyberattack on its systems.",
            "Chip shortages continue to constrain automotive production globally.",
            "A ransomware attack encrypted logistics management systems across the network.",
        ],
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# INDUSTRY TERMS FOR CO-OCCURRENCE MAPPING (Level 2, §7.4)
# ──────────────────────────────────────────────────────────────────────────────

INDUSTRY_KEYWORDS: dict[str, list[str]] = {
    "Steel":          ["steel", "iron ore", "blast furnace", "flat-rolled", "rebar", "coil"],
    "Automotive":     ["automotive", "vehicle", "toyota", "bmw", "volkswagen", "car", "ev",
                       "electric vehicle", "automaker"],
    "Semiconductors": ["semiconductor", "chip", "wafer", "tsmc", "intel", "fab", "silicon",
                       "microchip", "integrated circuit"],
    "Logistics":      ["port", "shipping", "container", "freight", "cargo", "vessel",
                       "logistics", "dhl", "fedex", "maersk"],
    "Energy":         ["oil", "gas", "lng", "fuel", "refinery", "pipeline", "energy",
                       "petrochemical", "crude"],
    "Agriculture":    ["wheat", "corn", "soybean", "grain", "harvest", "crop",
                       "agriculture", "food", "fertilizer"],
    "Mining":         ["mine", "mining", "ore", "lithium", "cobalt", "copper", "nickel",
                       "rare earth", "extraction"],
    "Pharmaceuticals":["pharma", "drug", "api", "medicine", "vaccine", "fda", "clinical"],
    "Electronics":    ["electronics", "pcb", "display", "battery", "consumer electronics",
                       "smartphone", "component"],
    "Construction":   ["construction", "cement", "concrete", "steel rebar", "building",
                       "infrastructure", "housing"],
}

# ──────────────────────────────────────────────────────────────────────────────
# RESULT TYPES
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TopicAssignment:
    """Topic assignment for a single article or cluster."""
    topic_id:        int          = -1   # -1 = outlier
    domain:          str          = "unknown"
    domain_label:    str          = "Unknown"
    confidence:      float        = 0.0
    industries:      list[str]    = field(default_factory=list)
    keywords_hit:    list[str]    = field(default_factory=list)


@dataclass
class TopicResult:
    """Return type from model_topics()."""
    assignments:          list[TopicAssignment]   # one per article
    cluster_assignments:  list[TopicAssignment]   # one per cluster
    topic_counts:         dict[str, int]          # domain → article count
    cross_industry_map:   dict[str, list]         # industry → [(industry, conf, count)]
    bertopic_available:   bool
    method:               str                     # "bertopic" | "keyword" | "cosine"


# ──────────────────────────────────────────────────────────────────────────────
# KEYWORD-BASED DOMAIN CLASSIFIER (fallback)
# ──────────────────────────────────────────────────────────────────────────────

def _text_for_article(article: dict) -> str:
    """Concatenate all useful text fields from an article dict."""
    parts = [
        article.get("title", ""),
        article.get("clean_title", ""),
        article.get("summary", ""),
        article.get("input_text", ""),
    ]
    # Include sentence text
    for s in article.get("sentences", []):
        parts.append(s)
    return " ".join(p for p in parts if p).lower()


def _keyword_domain_score(text: str, domain_key: str) -> tuple[float, list[str]]:
    """
    Score an article's text against a domain's keyword list.
    Returns (normalised_score, matched_keywords).
    """
    keywords = DISRUPTION_DOMAINS[domain_key]["keywords"]
    hits = []
    for kw in keywords:
        if kw.lower() in text:
            hits.append(kw)
    score = len(hits) / max(len(keywords), 1)
    return score, hits


def _assign_domain_keyword(text: str) -> TopicAssignment:
    """
    Assign the best-matching disruption domain to an article via keyword scoring.
    Falls back to 'unknown' if no keywords match at all.
    """
    best_domain = "unknown"
    best_score  = 0.0
    best_hits:  list[str] = []

    for domain_key, domain_data in DISRUPTION_DOMAINS.items():
        score, hits = _keyword_domain_score(text, domain_key)
        if score > best_score:
            best_score  = score
            best_domain = domain_key
            best_hits   = hits

    domain_data = DISRUPTION_DOMAINS.get(best_domain, {})
    industries  = _detect_industries(text)

    return TopicAssignment(
        topic_id     = -1 if best_score == 0 else hash(best_domain) % 1000,
        domain       = best_domain,
        domain_label = domain_data.get("label", "Unknown"),
        confidence   = round(min(best_score * 3.0, 1.0), 3),   # scale up from fraction
        industries   = industries,
        keywords_hit = best_hits[:8],
    )


def _detect_industries(text: str) -> list[str]:
    """
    Detect which industries are mentioned in the text via keyword matching.
    Returns a list of industry names (sorted by match count descending).
    """
    scores: dict[str, int] = {}
    text_lower = text.lower()
    for industry, kws in INDUSTRY_KEYWORDS.items():
        count = sum(1 for kw in kws if kw.lower() in text_lower)
        if count > 0:
            scores[industry] = count
    return sorted(scores, key=lambda i: -scores[i])


# ──────────────────────────────────────────────────────────────────────────────
# COSINE-BASED DOMAIN CLASSIFIER (uses SBERT archetypes when available)
# ──────────────────────────────────────────────────────────────────────────────

_domain_archetype_embeddings: Optional[dict[str, np.ndarray]] = None


def _get_domain_embeddings() -> Optional[dict[str, np.ndarray]]:
    """
    Build or return cached domain centroid embeddings from archetype sentences.
    Requires sentence-transformers.  Returns None if unavailable.
    """
    global _domain_archetype_embeddings
    if _domain_archetype_embeddings is not None:
        return _domain_archetype_embeddings

    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        embeddings = {}
        for domain_key, domain_data in DISRUPTION_DOMAINS.items():
            archetypes = domain_data.get("archetypes", [])
            if not archetypes:
                continue
            embs = model.encode(
                archetypes,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            centroid = embs.mean(axis=0)
            norm = np.linalg.norm(centroid)
            if norm > 0:
                centroid /= norm
            embeddings[domain_key] = centroid
        _domain_archetype_embeddings = embeddings
        logger.info(
            f"Topic modeller: computed archetype embeddings for "
            f"{len(embeddings)} disruption domains."
        )
        return _domain_archetype_embeddings
    except ImportError:
        logger.info("Topic modeller: sentence-transformers unavailable — using keyword fallback.")
        return None
    except Exception as e:
        logger.warning(f"Topic modeller: archetype embedding failed ({e}) — using keyword fallback.")
        return None


def _assign_domain_cosine(doc_embedding: list | np.ndarray, text: str) -> TopicAssignment:
    """
    Assign domain by cosine similarity to archetype centroids.
    Falls back to keyword scoring for industries and keyword_hits.
    """
    domain_embs = _get_domain_embeddings()
    if domain_embs is None or doc_embedding is None:
        return _assign_domain_keyword(text)

    emb = np.array(doc_embedding, dtype=np.float32)
    norm = np.linalg.norm(emb)
    if norm > 0:
        emb /= norm

    best_domain = "unknown"
    best_score  = -1.0
    for domain_key, centroid in domain_embs.items():
        sim = float(np.dot(emb, centroid))
        if sim > best_score:
            best_score  = sim
            best_domain = domain_key

    # Supplement with keyword hits for transparency
    _, kw_hits = _keyword_domain_score(text, best_domain)

    domain_data = DISRUPTION_DOMAINS.get(best_domain, {})
    industries  = _detect_industries(text)

    return TopicAssignment(
        topic_id     = hash(best_domain) % 1000,
        domain       = best_domain,
        domain_label = domain_data.get("label", best_domain),
        confidence   = round(max(0.0, best_score), 3),
        industries   = industries,
        keywords_hit = kw_hits[:8],
    )


# ──────────────────────────────────────────────────────────────────────────────
# BERTOPIC INTEGRATION (optional, full pipeline)
# ──────────────────────────────────────────────────────────────────────────────

def _run_bertopic(
    articles: list[dict],
    doc_embeddings: Optional[np.ndarray],
) -> Optional[list[TopicAssignment]]:
    """
    Run the full BERTopic pipeline on article texts.
    Returns a list of TopicAssignment objects (one per article), or None
    if BERTopic is not installed or fails.
    """
    try:
        from bertopic import BERTopic
        from umap import UMAP
        from hdbscan import HDBSCAN
    except ImportError:
        return None

    try:
        texts = [_text_for_article(a) for a in articles]
        if len(texts) < 5:
            logger.info("Topic modeller: fewer than 5 articles — skipping BERTopic.")
            return None

        umap_model  = UMAP(n_components=5, n_neighbors=5, min_dist=0.0, metric="cosine")
        hdbscan_model = HDBSCAN(
            min_cluster_size=2, min_samples=1,
            metric="euclidean", cluster_selection_method="eom"
        )
        topic_model = BERTopic(
            umap_model=umap_model,
            hdbscan_model=hdbscan_model,
            calculate_probabilities=True,
            verbose=False,
        )

        if doc_embeddings is not None and len(doc_embeddings) == len(texts):
            topics, probs = topic_model.fit_transform(texts, embeddings=doc_embeddings)
        else:
            topics, probs = topic_model.fit_transform(texts)

        # Map BERTopic topic IDs to our domain taxonomy
        assignments = []
        for i, (topic_id, art) in enumerate(zip(topics, articles)):
            text = _text_for_article(art)
            doc_emb = art.get("doc_embedding") or art.get("embedding")
            asgn = _assign_domain_cosine(doc_emb, text) if doc_emb else _assign_domain_keyword(text)
            asgn.topic_id = int(topic_id)
            asgn.confidence = round(float(max(probs[i])) if hasattr(probs[i], '__iter__') else float(probs[i]), 3)
            assignments.append(asgn)

        logger.info(
            f"BERTopic: fitted {len(set(topics))} topics from "
            f"{len(articles)} articles."
        )
        return assignments

    except Exception as e:
        logger.warning(f"BERTopic pipeline failed ({e}) — falling back to cosine/keyword.")
        return None


# ──────────────────────────────────────────────────────────────────────────────
# CROSS-INDUSTRY MAP (§7.4)
# ──────────────────────────────────────────────────────────────────────────────

def build_cross_industry_map(
    topic_result: TopicResult,
    min_count: int = 2,
) -> dict[str, list[tuple[str, float, int]]]:
    """
    Build a cross-industry co-occurrence map from topic assignments.

    For each pair of industries (A, B), count how many articles or clusters
    mention both.  The confidence is count / total_articles_mentioning_A.

    Returns:
        {industry_A: [(industry_B, confidence, co_occurrence_count), ...]}
    Each list is sorted by confidence descending.

    Parameters
    ──────────
    topic_result  TopicResult from model_topics().
    min_count     Minimum co-occurrence count to include a link.
    """
    # Collect all (industry_list) from article-level assignments
    industry_lists = [a.industries for a in topic_result.assignments]

    # Count per-industry article volumes
    industry_totals: dict[str, int] = Counter(
        ind for inds in industry_lists for ind in inds
    )

    # Count co-occurrences
    pair_counts: dict[tuple[str, str], int] = Counter()
    for inds in industry_lists:
        unique = list(dict.fromkeys(inds))  # preserve order, deduplicate
        for i in range(len(unique)):
            for j in range(len(unique)):
                if i != j:
                    pair_counts[(unique[i], unique[j])] += 1

    cross_map: dict[str, list] = defaultdict(list)
    for (src, tgt), count in pair_counts.items():
        if count < min_count:
            continue
        total_src = industry_totals.get(src, 1)
        confidence = round(count / total_src, 3)
        cross_map[src].append((tgt, confidence, count))

    # Sort each list by confidence desc
    for src in cross_map:
        cross_map[src].sort(key=lambda x: -x[1])

    return dict(cross_map)


# ──────────────────────────────────────────────────────────────────────────────
# CLUSTER-LEVEL TOPIC ASSIGNMENT
# ──────────────────────────────────────────────────────────────────────────────

def _assign_cluster_topic(
    cluster: dict,
    article_assignments: list[TopicAssignment],
    article_idx_map: dict[str, int],
) -> TopicAssignment:
    """
    Assign a domain to a cluster by majority vote over its member articles'
    assignments.
    """
    cluster_arts = cluster.get("articles", [])
    domain_votes: Counter = Counter()
    all_industries: list[str] = []
    all_kw_hits:    list[str] = []
    best_conf = 0.0

    for art in cluster_arts:
        url = art.get("url", "")
        idx = article_idx_map.get(url)
        if idx is not None and idx < len(article_assignments):
            asgn = article_assignments[idx]
            domain_votes[asgn.domain] += 1
            all_industries.extend(asgn.industries)
            all_kw_hits.extend(asgn.keywords_hit)
            if asgn.confidence > best_conf:
                best_conf = asgn.confidence

    if not domain_votes:
        # Fallback: assign from cluster text directly
        text = " ".join(
            a.get("title", "") + " " + a.get("summary", "")
            for a in cluster_arts
        )
        doc_emb = cluster_arts[0].get("doc_embedding") if cluster_arts else None
        return _assign_domain_cosine(doc_emb, text)

    best_domain, _ = domain_votes.most_common(1)[0]
    domain_data    = DISRUPTION_DOMAINS.get(best_domain, {})

    # Deduplicate industry list, keep order, take top 5
    seen_ind:   set[str] = set()
    uniq_inds:  list[str] = []
    for ind in all_industries:
        if ind not in seen_ind:
            seen_ind.add(ind)
            uniq_inds.append(ind)

    return TopicAssignment(
        topic_id     = hash(best_domain) % 1000,
        domain       = best_domain,
        domain_label = domain_data.get("label", best_domain),
        confidence   = round(best_conf, 3),
        industries   = uniq_inds[:5],
        keywords_hit = list(dict.fromkeys(all_kw_hits))[:8],
    )


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────────────────────────────────────

def model_topics(
    clusters: list[dict],
    articles: list[dict],
) -> TopicResult:
    """
    Assign disruption domain topics to articles and clusters.

    Tries in order:
      1. BERTopic full pipeline (if bertopic + umap + hdbscan installed)
      2. Cosine similarity to archetype centroids (if sentence-transformers)
      3. Pure keyword matching (always available)

    Parameters
    ──────────
    clusters  Cluster list from event_clusterer (after attach_summaries / attach_briefs).
    articles  Flat list of all deduplicated articles (with SBERT fields injected).

    Returns
    ───────
    TopicResult with per-article and per-cluster assignments.
    """
    if not articles:
        return TopicResult(
            assignments=[],
            cluster_assignments=[],
            topic_counts={},
            cross_industry_map={},
            bertopic_available=False,
            method="none",
        )

    # ── Attempt BERTopic ────────────────────────────────────────────────────
    doc_embeddings = None
    emb_list = [a.get("doc_embedding") or a.get("embedding") for a in articles]
    if all(e is not None for e in emb_list):
        try:
            doc_embeddings = np.array(emb_list, dtype=np.float32)
        except Exception:
            pass

    bertopic_assignments = _run_bertopic(articles, doc_embeddings)
    bertopic_available   = bertopic_assignments is not None
    method               = "bertopic"

    if bertopic_assignments:
        article_assignments = bertopic_assignments
    else:
        # ── Cosine / keyword fallback ─────────────────────────────────────
        article_assignments = []
        for art in articles:
            text    = _text_for_article(art)
            doc_emb = art.get("doc_embedding") or art.get("embedding")
            if doc_emb is not None:
                asgn   = _assign_domain_cosine(doc_emb, text)
                method = "cosine"
            else:
                asgn   = _assign_domain_keyword(text)
                method = "keyword" if method == "bertopic" else method
            article_assignments.append(asgn)

    # ── Build URL→index map for cluster assignment ───────────────────────
    url_to_idx = {a.get("url", ""): i for i, a in enumerate(articles)}

    # ── Cluster-level assignments ─────────────────────────────────────────
    cluster_assignments = [
        _assign_cluster_topic(c, article_assignments, url_to_idx)
        for c in clusters
    ]

    # ── Topic counts ─────────────────────────────────────────────────────
    topic_counts: dict[str, int] = Counter(a.domain for a in article_assignments)

    # ── Cross-industry map ────────────────────────────────────────────────
    result = TopicResult(
        assignments          = article_assignments,
        cluster_assignments  = cluster_assignments,
        topic_counts         = dict(topic_counts),
        cross_industry_map   = {},
        bertopic_available   = bertopic_available,
        method               = method,
    )
    result.cross_industry_map = build_cross_industry_map(result)

    logger.info(
        f"Topic modelling complete ({method}) — "
        f"{len(articles)} articles → {len(topic_counts)} domain(s) "
        f"[{', '.join(f'{d}:{n}' for d, n in topic_counts.most_common(3))}]"
    )
    return result


def attach_topics(
    clusters: list[dict],
    articles: list[dict],
) -> TopicResult:
    """
    Convenience wrapper: run model_topics() and inject topic fields
    back into cluster and article dicts in-place.

    Adds to each article dict:
      - topic_domain        : str   (e.g. "geopolitical")
      - topic_domain_label  : str   (e.g. "Geopolitical / Trade Policy")
      - topic_confidence    : float
      - topic_industries    : list[str]
      - topic_keywords_hit  : list[str]

    Adds to each cluster dict:
      - topic_domain        : str
      - topic_domain_label  : str
      - topic_confidence    : float
      - topic_industries    : list[str]

    Returns the TopicResult.
    """
    result = model_topics(clusters, articles)

    for art, asgn in zip(articles, result.assignments):
        art["topic_domain"]       = asgn.domain
        art["topic_domain_label"] = asgn.domain_label
        art["topic_confidence"]   = asgn.confidence
        art["topic_industries"]   = asgn.industries
        art["topic_keywords_hit"] = asgn.keywords_hit

    for cluster, asgn in zip(clusters, result.cluster_assignments):
        cluster["topic_domain"]       = asgn.domain
        cluster["topic_domain_label"] = asgn.domain_label
        cluster["topic_confidence"]   = asgn.confidence
        cluster["topic_industries"]   = asgn.industries

    return result
"""
utils/risk_engine.py
─────────────────────────────────────────────────────────────────────────────
Advanced composite risk scoring engine for the Supply Chain Disruption
Intelligence System.

Implements the five-dimension scoring framework described in §8 of the
system documentation:

  Dimension         Weight   How measured
  ──────────────    ──────   ────────────────────────────────────────────────
  Severity           7.0     Language intensity from article text + impact_level
  Propagation        8.0     Downstream industries affected (from topic_industries)
  Concentration      6.5     Geographic / supplier concentration factor
  Velocity           7.8     Article volume growth rate within the cluster
  Verification       boost   Confidence multiplier from analyst verification status

Final score = weighted average × verification_multiplier → 0.0–10.0

Also provides:
  compute_cluster_risk(cluster, topic_result)     → enriched cluster dict
  compute_overall_risk(clusters, deduped_articles) → (level, message, score_0_100)
  enrich_clusters_with_risk(clusters, topic_result, articles)  → mutates in-place

Public API
──────────
  enrich_clusters_with_risk(clusters, topic_result, articles)
      Main entry point.  Mutates cluster dicts to add composite_risk_score
      (0.0–10.0), risk_level, and scoring breakdown.
      Returns the clusters list.

  compute_overall_risk(clusters, articles)
      Compute dashboard-level overall risk badge.
      Returns (overall_risk: str, risk_message: str, risk_score_0_100: int).
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from typing import Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# SEVERITY LANGUAGE LEXICONS
# ──────────────────────────────────────────────────────────────────────────────

_HIGH_SEVERITY_PHRASES = [
    "complete halt", "full shutdown", "indefinitely suspended",
    "catastrophic", "major disruption", "critical shortage",
    "emergency", "force majeure", "grounded", "closure",
    "explosion", "collapsed", "destroyed", "blocked",
    "immediate effect", "effective immediately",
]

_MEDIUM_SEVERITY_PHRASES = [
    "significant delay", "reduced capacity", "slowdown",
    "disrupted", "affected", "constrained", "impacted",
    "shortfall", "supply chain risk", "concerns",
    "warning", "alert", "monitoring", "uncertainty",
]

_LOW_SEVERITY_PHRASES = [
    "minor delay", "slight", "marginal", "modest",
    "watching closely", "potential risk", "possible",
]

# Propagation scores: how many downstream industries does each domain typically affect
_DOMAIN_PROPAGATION: dict[str, float] = {
    "infrastructure":    8.5,   # all sea freight dependent
    "geopolitical":      8.0,   # energy, metals, agriculture all affected
    "cyber_technology":  8.0,   # semiconductors, automotive, finance
    "labor":             7.0,   # logistics, automotive, energy
    "natural_disaster":  7.0,   # mining, agriculture, logistics
    "financial":         7.5,   # all commodity-intensive sectors
    "pandemic_health":   8.0,   # pharma, food, electronics, logistics
    "regulatory":        5.5,   # pharma, chemicals, agriculture, automotive
    "unknown":           4.0,
}

# Geographic concentration factors (fraction of global production in top region)
# Higher value = higher risk when that region is disrupted
_COMMODITY_CONCENTRATION: dict[str, float] = {
    "lithium":              1.8,   # 90%+ refining in China
    "rare earth":           1.9,   # ~90% in China
    "cobalt":               1.7,   # ~70% in DRC
    "semiconductor":        1.6,   # TSMC / ASML concentration
    "steel":                1.3,   # China = 57% of global
    "iron ore":             1.2,
    "copper":               1.1,
    "oil":                  1.1,
    "gas":                  1.1,
    "wheat":                1.1,
    "default":              1.0,
}


# ──────────────────────────────────────────────────────────────────────────────
# DIMENSION 1: SEVERITY
# ──────────────────────────────────────────────────────────────────────────────

def _severity_from_text(articles: list[dict]) -> float:
    """
    Score severity (0.0–10.0) from combined article text, impact_level counts,
    and disruption-intensity language.
    """
    if not articles:
        return 0.0

    # Base from impact_level distribution
    high_n   = sum(1 for a in articles if a.get("impact_level") == "HIGH")
    med_n    = sum(1 for a in articles if a.get("impact_level") == "MEDIUM")
    total    = len(articles)

    level_score = (high_n * 9.0 + med_n * 5.0) / max(total, 1)

    # Language intensity boost from combined title + summary text
    combined_text = " ".join(
        (a.get("title", "") + " " + a.get("summary", "")).lower()
        for a in articles
    )

    phrase_score = 0.0
    for phrase in _HIGH_SEVERITY_PHRASES:
        if phrase in combined_text:
            phrase_score += 0.5
    for phrase in _MEDIUM_SEVERITY_PHRASES:
        if phrase in combined_text:
            phrase_score += 0.2
    phrase_score = min(phrase_score, 3.0)   # cap phrase boost

    # Relevance score contribution
    avg_relevance = sum(a.get("relevance_score", 0) for a in articles) / max(total, 1)
    rel_score     = (avg_relevance / 100.0) * 10.0

    raw = (level_score * 0.5) + (phrase_score * 0.3) + (rel_score * 0.2)
    return round(min(raw, 10.0), 2)


# ──────────────────────────────────────────────────────────────────────────────
# DIMENSION 2: PROPAGATION
# ──────────────────────────────────────────────────────────────────────────────

def _propagation_score(cluster: dict, topic_industries: list[str]) -> float:
    """
    Score propagation (0.0–10.0) from domain type and number of affected industries.
    More downstream industries = higher propagation risk.
    """
    domain = cluster.get("topic_domain", "unknown")
    base   = _DOMAIN_PROPAGATION.get(domain, 4.0)

    # Each additional industry detected adds a small boost
    n_industries = len(topic_industries)
    industry_boost = min(n_industries * 0.4, 2.0)

    return round(min(base + industry_boost, 10.0), 2)


# ──────────────────────────────────────────────────────────────────────────────
# DIMENSION 3: CONCENTRATION
# ──────────────────────────────────────────────────────────────────────────────

def _concentration_factor(cluster: dict) -> float:
    """
    Returns the geographic/commodity concentration multiplier (1.0–2.0).
    Checks linked_nodes and topic_industries for high-concentration commodities.
    """
    factor = 1.0

    nodes = cluster.get("linked_nodes", [])
    node_text = " ".join(n.lower() for n in nodes)

    for commodity, conc in _COMMODITY_CONCENTRATION.items():
        if commodity in node_text:
            factor = max(factor, conc)

    industries = cluster.get("topic_industries", [])
    for ind in industries:
        ind_lower = ind.lower()
        for commodity, conc in _COMMODITY_CONCENTRATION.items():
            if commodity in ind_lower:
                factor = max(factor, conc)

    return round(factor, 2)


def _concentration_score(base_severity: float, factor: float) -> float:
    """Convert concentration factor into a 0–10 score."""
    return round(min(base_severity * factor, 10.0), 2)


# ──────────────────────────────────────────────────────────────────────────────
# DIMENSION 4: VELOCITY
# ──────────────────────────────────────────────────────────────────────────────

def _velocity_score(cluster: dict) -> float:
    """
    Score velocity (0.0–10.0) based on article count relative to cluster size.

    Since we don't have intra-day time series in this batch, we use
    article_count as a proxy — more articles covering the same event within
    the same fetch window = higher velocity / newsworthiness signal.

    True hourly velocity tracking would require time-stamped run comparison
    (see cross_cluster_dedup.py for run-over-run logic).
    """
    n = cluster.get("article_count", 1)

    # Article count tiers (empirically tuned):
    # 1 article  → 1.0  (very low velocity)
    # 3-5        → 4.0
    # 6-10       → 6.5
    # 11-20      → 8.0
    # 20+        → 9.5

    if n >= 20:
        return 9.5
    elif n >= 11:
        return 8.0
    elif n >= 6:
        return 6.5
    elif n >= 3:
        return 4.0
    else:
        return round(n * 1.0, 2)


# ──────────────────────────────────────────────────────────────────────────────
# DIMENSION 5: VERIFICATION MULTIPLIER
# ──────────────────────────────────────────────────────────────────────────────

def _verification_multiplier(articles: list[dict]) -> float:
    """
    Compute confidence multiplier based on analyst verification status.

    As per §8.1 documentation:
      0 verified articles    → 0.90  (unverified penalty)
      ≥1 partially verified  → 1.00  (neutral)
      All fully verified     → 1.10  (verified bonus)
      Any rejected           → 0.80  (rejection penalty)
    """
    total    = len(articles)
    if total == 0:
        return 0.90

    verified = sum(1 for a in articles if a.get("verified", False))
    rejected = sum(1 for a in articles if a.get("rejected", False))

    if rejected > 0:
        return 0.80   # contaminated by rejected articles

    if verified == 0:
        return 0.90   # all unverified

    fraction_verified = verified / total
    if fraction_verified >= 1.0:
        return 1.10
    elif fraction_verified >= 0.5:
        return 1.05
    else:
        return 1.00


# ──────────────────────────────────────────────────────────────────────────────
# COMPOSITE SCORE CALCULATION
# ──────────────────────────────────────────────────────────────────────────────

def _risk_level(score: float) -> str:
    """Map 0–10 score to risk level label."""
    if score >= 8.0:
        return "CRITICAL"
    elif score >= 6.0:
        return "HIGH"
    elif score >= 3.5:
        return "MEDIUM"
    else:
        return "LOW"


def compute_cluster_risk(cluster: dict) -> dict:
    """
    Compute the composite risk score for a single cluster and inject
    risk fields into the cluster dict.

    Expects the cluster to already have topic fields injected by
    topic_modeller.attach_topics().

    Returns the enriched cluster dict (also mutated in-place).
    """
    articles = cluster.get("articles", [])
    topic_industries = cluster.get("topic_industries", [])

    # ── Five dimensions ───────────────────────────────────────────────────
    sev  = _severity_from_text(articles)
    prop = _propagation_score(cluster, topic_industries)
    conc_factor = _concentration_factor(cluster)
    conc = _concentration_score(sev, conc_factor)
    vel  = _velocity_score(cluster)
    ver  = _verification_multiplier(articles)

    # Raw composite: simple mean of four measurable dimensions
    raw = (sev + prop + conc + vel) / 4.0

    # Apply verification multiplier
    final = round(min(raw * ver, 10.0), 2)

    level = _risk_level(final)

    cluster["composite_risk_score"] = final
    cluster["risk_level"]           = level
    cluster["risk_breakdown"] = {
        "severity":               sev,
        "propagation":            prop,
        "concentration_factor":   conc_factor,
        "concentration_score":    conc,
        "velocity":               vel,
        "verification_multiplier": ver,
        "raw_score":              round(raw, 2),
        "final_score":            final,
    }

    logger.debug(
        f"Cluster {cluster.get('cluster_id')} risk: "
        f"sev={sev} prop={prop} conc={conc} vel={vel} × ver={ver} → {final} [{level}]"
    )
    return cluster


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC: ENRICH CLUSTERS
# ──────────────────────────────────────────────────────────────────────────────

def enrich_clusters_with_risk(
    clusters: list[dict],
    articles: list[dict],
) -> list[dict]:
    """
    Run the full risk scoring pipeline over all clusters.

    Expects:
      - clusters enriched by topic_modeller.attach_topics()
        (topic_domain, topic_industries fields present)
      - articles with verified/rejected fields (may be absent → treated as False)

    Mutates each cluster dict in-place to add:
      - composite_risk_score  float  (0.0–10.0)
      - risk_level            str    ("LOW" / "MEDIUM" / "HIGH" / "CRITICAL")
      - risk_breakdown        dict   (per-dimension breakdown)

    Also updates cluster["impact_level"] to match risk_level for
    backward compatibility with the dashboard.

    Returns the clusters list.
    """
    for cluster in clusters:
        compute_cluster_risk(cluster)
        # Keep impact_level aligned with composite risk
        cluster["impact_level"] = cluster["risk_level"]

    n_critical = sum(1 for c in clusters if c.get("risk_level") == "CRITICAL")
    n_high     = sum(1 for c in clusters if c.get("risk_level") == "HIGH")
    n_medium   = sum(1 for c in clusters if c.get("risk_level") == "MEDIUM")

    logger.info(
        f"Risk engine: {len(clusters)} cluster(s) scored — "
        f"CRITICAL:{n_critical} HIGH:{n_high} MEDIUM:{n_medium}"
    )
    return clusters


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC: OVERALL DASHBOARD RISK
# ──────────────────────────────────────────────────────────────────────────────

def compute_overall_risk(
    clusters: list[dict],
    articles: list[dict],
) -> tuple[str, str, int]:
    """
    Compute dashboard-level overall risk badge from cluster scores.

    Returns (overall_risk: str, risk_message: str, risk_score_0_100: int)
    where risk_score_0_100 is the 0–100 scale used by the frontend gauge.
    """
    if not clusters and not articles:
        return "LOW", "No articles retrieved for this profile.", 0

    # Use composite_risk_score if available, fall back to legacy counting
    scored = [c for c in clusters if "composite_risk_score" in c and not c.get("is_noise")]

    if scored:
        max_score    = max(c["composite_risk_score"] for c in scored)
        avg_score    = sum(c["composite_risk_score"] for c in scored) / len(scored)
        n_critical   = sum(1 for c in scored if c.get("risk_level") == "CRITICAL")
        n_high       = sum(1 for c in scored if c.get("risk_level") == "HIGH")

        # Convert 0-10 to 0-100 for gauge
        risk_score_100 = min(int(max_score * 10), 100)

        if max_score >= 8.0 or n_critical >= 1:
            return (
                "HIGH",
                (
                    f"Critical supply chain disruption detected. "
                    f"{n_critical + n_high} high-severity event(s) across monitored nodes. "
                    "Immediate escalation recommended."
                ),
                risk_score_100,
            )
        elif max_score >= 6.0 or n_high >= 1:
            return (
                "MEDIUM",
                (
                    f"Elevated disruption risk across {n_high} event cluster(s). "
                    "Monitor closely and assess supplier contingency plans."
                ),
                risk_score_100,
            )
        else:
            return (
                "LOW",
                "No significant disruption signals detected for current exposure profile.",
                risk_score_100,
            )

    # Legacy fallback (no composite scores)
    high_count   = sum(1 for a in articles if a.get("impact_level") == "HIGH")
    medium_count = sum(1 for a in articles if a.get("impact_level") == "MEDIUM")
    risk_score   = min(high_count * 20 + medium_count * 10, 100)

    if high_count >= 5:
        return (
            "HIGH",
            "Multiple high-impact disruptions detected across supply chain exposure. "
            "Immediate review recommended.",
            risk_score,
        )
    elif high_count >= 1:
        return (
            "MEDIUM",
            "Potentially disruptive events detected affecting one or more supply chain nodes. "
            "Monitor closely.",
            risk_score,
        )
    else:
        return "LOW", "No significant disruption signals detected currently.", risk_score
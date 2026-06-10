"""
utils/risk_scorer.py
─────────────────────────────────────────────────────────────────────────────
8-dimension composite risk scorer for supply chain event clusters.

Replaces the naive high_count * 20 + medium_count * 10 formula in app.py
with a weighted composite that captures signal quality, breadth, node
criticality, geographic spread, corroboration, velocity, cluster size,
and semantic confidence.

Scoring dimensions (all normalised to 0–100 before weighting)
─────────────────────────────────────────────────────────────
  D1  Signal intensity     25%  max relevance_score in cluster
  D2  Signal breadth       15%  distinct disruption domains triggered
  D3  Node criticality     20%  tier of highest-value node at risk
  D4  Geographic spread    10%  distinct countries affected
  D5  Source corroboration 10%  distinct sources / outlets
  D6  Velocity             10%  articles in last 24h / total articles
  D7  Cluster size          5%  article count (log-scaled)
  D8  Semantic confidence   5%  mean relevance_score across cluster

Severity bands
──────────────
  CRITICAL  ≥ 75
  HIGH      ≥ 55
  MEDIUM    ≥ 35
  LOW       <  35

Public API
──────────
  score_cluster(cluster)           → ClusterRiskScore
  score_all_clusters(clusters)     → list[dict]   (mutates in-place)
  portfolio_risk(clusters)         → PortfolioRisk
"""

from __future__ import annotations

import math
import logging
from collections  import Counter
from dataclasses  import dataclass, field
from datetime     import datetime, timezone, timedelta
from typing       import Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# WEIGHTS  (must sum to 1.0)
# ──────────────────────────────────────────────────────────────────────────────

_W = {
    "intensity":     0.25,
    "breadth":       0.15,
    "node_crit":     0.20,
    "geo_spread":    0.10,
    "corroboration": 0.10,
    "velocity":      0.10,
    "cluster_size":  0.05,
    "sem_confidence":0.05,
}

# ──────────────────────────────────────────────────────────────────────────────
# SEVERITY BANDS
# ──────────────────────────────────────────────────────────────────────────────

def _severity(score: float) -> str:
    if score >= 75: return "CRITICAL"
    if score >= 55: return "HIGH"
    if score >= 35: return "MEDIUM"
    return "LOW"


# ──────────────────────────────────────────────────────────────────────────────
# NODE CRITICALITY TIERS
# linked_nodes entries are typed "supplier:X", "material:X", "port:X", "route:X"
# ──────────────────────────────────────────────────────────────────────────────

_NODE_TIER = {
    "supplier": 100,
    "material": 80,
    "port":     60,
    "route":    40,
    "country":  20,
}


# ──────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ClusterRiskScore:
    composite:        float
    severity:         str
    dimension_scores: dict
    narrative:        str


@dataclass
class PortfolioRisk:
    overall_score:    float
    overall_severity: str
    risk_message:     str
    critical_count:   int
    high_count:       int
    medium_count:     int
    low_count:        int
    top_clusters:     list
    domain_breakdown: dict

    def to_dict(self) -> dict:
        return {
            "overall_score":    round(self.overall_score, 1),
            "overall_severity": self.overall_severity,
            "risk_message":     self.risk_message,
            "critical_count":   self.critical_count,
            "high_count":       self.high_count,
            "medium_count":     self.medium_count,
            "low_count":        self.low_count,
            "top_clusters":     self.top_clusters,
            "domain_breakdown": self.domain_breakdown,
        }


# ──────────────────────────────────────────────────────────────────────────────
# DIMENSION HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _d1_intensity(articles: list) -> float:
    if not articles:
        return 0.0
    return float(max(a.get("relevance_score", 0) for a in articles))


def _d2_breadth(articles: list) -> float:
    domains: set = set()
    for a in articles:
        for d in a.get("disruption_domains", []):
            if d:
                domains.add(d.lower())
    n = len(domains)
    return min(n * 20, 100)


def _d3_node_criticality(cluster: dict) -> float:
    best = 0
    for node in cluster.get("linked_nodes", []):
        prefix = node.split(":", 1)[0].lower() if ":" in node else ""
        tier   = _NODE_TIER.get(prefix, 0)
        if tier > best:
            best = tier
    return float(best)


def _d4_geo_spread(articles: list) -> float:
    countries = {a.get("country", "").strip() for a in articles if a.get("country")}
    countries.discard("")
    return min(len(countries) * 20, 100)


def _d5_corroboration(cluster: dict) -> float:
    sources = cluster.get("sources", [])
    n = len(set(sources))
    if n == 0: return 0.0
    if n == 1: return 10.0
    if n == 2: return 30.0
    if n == 3: return 50.0
    if n == 4: return 70.0
    if n == 5: return 90.0
    return 100.0


def _d6_velocity(articles: list) -> float:
    if not articles:
        return 0.0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent = 0
    for a in articles:
        pub = a.get("published") or a.get("published_at", "")
        if not pub:
            continue
        try:
            dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            if dt >= cutoff:
                recent += 1
        except ValueError:
            pass
    return round(recent / len(articles) * 100, 1)


def _d7_cluster_size(articles: list) -> float:
    n = len(articles)
    if n == 0:
        return 0.0
    return min(math.log2(n + 1) / math.log2(33) * 100, 100)


def _d8_sem_confidence(articles: list) -> float:
    if not articles:
        return 0.0
    scores = [a.get("relevance_score", 0) for a in articles]
    return round(sum(scores) / len(scores), 1)


# ──────────────────────────────────────────────────────────────────────────────
# NARRATIVE BUILDER  (no LLM — template-based)
# ──────────────────────────────────────────────────────────────────────────────

def _build_narrative(cluster: dict, dims: dict, severity: str, composite: float) -> str:
    articles = cluster.get("articles", [])

    intensity = dims["intensity"]
    if intensity >= 75:
        signal_str = "high-intensity"
    elif intensity >= 50:
        signal_str = "moderate"
    else:
        signal_str = "low-level"

    domain_counts: Counter = Counter()
    for a in articles:
        for d in a.get("disruption_domains", []):
            if d:
                domain_counts[d.lower()] += 1
    primary_domain = domain_counts.most_common(1)[0][0] if domain_counts else None

    top_node = ""
    best_tier = 0
    for node in cluster.get("linked_nodes", []):
        if ":" in node:
            prefix, name = node.split(":", 1)
            tier = _NODE_TIER.get(prefix.lower(), 0)
            if tier > best_tier:
                best_tier = tier
                top_node  = name

    n_sources = len(set(cluster.get("sources", [])))
    source_str = f"corroborated by {n_sources} source{'s' if n_sources != 1 else ''}"

    countries = list({
        a.get("country", "").strip()
        for a in articles if a.get("country", "").strip()
    })[:2]
    geo_str = f" in {', '.join(countries)}" if countries else ""

    parts = [f"{severity.title()} composite risk ({composite:.0f}/100)"]
    if primary_domain:
        parts.append(f"{signal_str} {primary_domain} signal")
    if top_node:
        parts.append(f"affecting {top_node}{geo_str}")
    parts.append(source_str)

    return " — ".join(parts) + "."


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC: score_cluster
# ──────────────────────────────────────────────────────────────────────────────

def score_cluster(cluster: dict) -> ClusterRiskScore:
    articles = cluster.get("articles", [])

    dims = {
        "intensity":      _d1_intensity(articles),
        "breadth":        _d2_breadth(articles),
        "node_crit":      _d3_node_criticality(cluster),
        "geo_spread":     _d4_geo_spread(articles),
        "corroboration":  _d5_corroboration(cluster),
        "velocity":       _d6_velocity(articles),
        "cluster_size":   _d7_cluster_size(articles),
        "sem_confidence": _d8_sem_confidence(articles),
    }

    composite = sum(_W[k] * v for k, v in dims.items())
    composite = round(min(composite, 100), 1)
    sev       = _severity(composite)
    narrative = _build_narrative(cluster, dims, sev, composite)

    return ClusterRiskScore(
        composite        = composite,
        severity         = sev,
        dimension_scores = {k: round(v, 1) for k, v in dims.items()},
        narrative        = narrative,
    )


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC: score_all_clusters
# ──────────────────────────────────────────────────────────────────────────────

def score_all_clusters(clusters: list) -> list:
    for cluster in clusters:
        result = score_cluster(cluster)
        cluster["composite_score"]  = result.composite
        cluster["severity"]         = result.severity
        cluster["dimension_scores"] = result.dimension_scores
        cluster["risk_narrative"]   = result.narrative

    _sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    clusters.sort(key=lambda c: (
        _sev_order.get(c.get("severity", "LOW"), 3),
        -c.get("composite_score", 0),
    ))

    counts = Counter(c.get("severity", "LOW") for c in clusters if not c.get("is_noise"))
    logger.info(
        f"risk_scorer: CRITICAL={counts['CRITICAL']} HIGH={counts['HIGH']} "
        f"MEDIUM={counts['MEDIUM']} LOW={counts['LOW']} "
        f"(noise singletons excluded)"
    )
    return clusters


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC: portfolio_risk
# ──────────────────────────────────────────────────────────────────────────────

def portfolio_risk(clusters: list) -> PortfolioRisk:
    _sev_weight = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}

    real_clusters = [c for c in clusters if not c.get("is_noise", False)]

    if real_clusters:
        total_weight = sum(_sev_weight.get(c.get("severity", "LOW"), 1)
                           for c in real_clusters)
        weighted_sum = sum(
            c.get("composite_score", 0) * _sev_weight.get(c.get("severity", "LOW"), 1)
            for c in real_clusters
        )
        overall_score = round(weighted_sum / total_weight, 1)
    else:
        overall_score = 0.0

    sev = _severity(overall_score)

    crit_n   = sum(1 for c in real_clusters if c.get("severity") == "CRITICAL")
    high_n   = sum(1 for c in real_clusters if c.get("severity") == "HIGH")
    med_n    = sum(1 for c in real_clusters if c.get("severity") == "MEDIUM")
    low_n    = sum(1 for c in real_clusters if c.get("severity") == "LOW")

    if sev == "CRITICAL":
        msg = (f"{crit_n} critical and {high_n} high-severity event"
               f"{'s' if crit_n+high_n != 1 else ''} detected. "
               "Immediate executive review required.")
    elif sev == "HIGH":
        msg = (f"{high_n} high-severity event{'s' if high_n != 1 else ''} detected "
               "across your supply chain exposure. Prompt review recommended.")
    elif sev == "MEDIUM":
        msg = (f"{med_n} medium-severity event{'s' if med_n != 1 else ''} identified. "
               "Monitor developments and review affected nodes.")
    else:
        msg = "No significant disruption signals detected across your supply chain."

    sorted_real = sorted(real_clusters, key=lambda c: -c.get("composite_score", 0))
    top_clusters = [
        {
            "cluster_id":      c.get("cluster_id"),
            "headline":        (
                (c.get("brief") or {}).get("headline")
                or (c.get("articles") or [{}])[0].get("title", "")
            ),
            "severity":        c.get("severity", "LOW"),
            "composite_score": c.get("composite_score", 0),
            "article_count":   c.get("article_count", 0),
            "risk_narrative":  c.get("risk_narrative", ""),
        }
        for c in sorted_real[:3]
    ]

    domain_counts: Counter = Counter()
    for c in clusters:
        for art in c.get("articles", []):
            for d in art.get("disruption_domains", []):
                if d:
                    domain_counts[d.lower()] += 1

    return PortfolioRisk(
        overall_score    = overall_score,
        overall_severity = sev,
        risk_message     = msg,
        critical_count   = crit_n,
        high_count       = high_n,
        medium_count     = med_n,
        low_count        = low_n,
        top_clusters     = top_clusters,
        domain_breakdown = dict(domain_counts.most_common()),
    )
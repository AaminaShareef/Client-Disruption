"""
utils/corpus_exporter.py
─────────────────────────────────────────────────────────────────────────────
Reads a saved analysis run and produces a labelled JSONL corpus for ML
training / fine-tuning pipelines.

Six label types per Section 10.2:
    1. industry_label      — keyword-mapped industry classification
    2. disruption_domain   — primary domain from disruption_domains list
    3. risk_score_norm     — continuous 0.0–1.0 regression target
    4. extractive_summary  — MMR-selected sentences (or fallback)
    5. ner_tags            — spaCy entity list [{text, label}]
    6. is_relevant         — binary 1/0 based on impact_level

Zero new dependencies — stdlib only.
"""

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone


# ─────────────────────────────────────────────────────────────────────────────
#  Industry keyword map
# ─────────────────────────────────────────────────────────────────────────────

_INDUSTRY_MAP: dict[str, list[str]] = {
    "energy":         ["lng", "oil", "gas", "refinery", "pipeline", "energy",
                       "petroleum", "fuel", "power", "electricity", "solar", "wind"],
    "mining":         ["lithium", "cobalt", "nickel", "copper", "iron ore",
                       "coal", "gold", "silver", "mining", "mine", "smelter"],
    "semiconductors": ["semiconductor", "chip", "wafer", "fab", "tsmc",
                       "foundry", "silicon", "microchip", "processor"],
    "logistics":      ["port", "shipping", "container", "freight", "carrier",
                       "vessel", "tanker", "rail", "trucking", "last mile"],
    "agriculture":    ["wheat", "corn", "soy", "grain", "fertilizer",
                       "crop", "harvest", "drought", "food supply"],
    "manufacturing":  ["factory", "plant", "assembly", "production line",
                       "oem", "tier-1", "supplier", "component"],
    "financial":      ["tariff", "sanctions", "currency", "forex",
                       "inflation", "interest rate", "credit"],
}


def _classify_industry(title: str, body: str) -> str:
    """
    Pure keyword match against title + clean_body (lowercased).
    First matching industry wins; returns "general" if no match.
    Multi-word keywords (e.g. "iron ore") are checked with substring search.
    """
    haystack = f"{title} {body}".lower()
    for industry, keywords in _INDUSTRY_MAP.items():
        for kw in keywords:
            # word-boundary-aware match for single-word kw, substring for multi-word
            if " " in kw:
                if kw in haystack:
                    return industry
            else:
                if re.search(r"\b" + re.escape(kw) + r"\b", haystack):
                    return industry
    return "general"


# ─────────────────────────────────────────────────────────────────────────────
#  CorpusExport dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CorpusExport:
    articles:       list[dict]
    run_id:         str
    exported_at:    str
    total:          int
    by_industry:    dict[str, int]
    by_domain:      dict[str, int]
    by_impact:      dict[str, int]
    relevant_ratio: float


# ─────────────────────────────────────────────────────────────────────────────
#  Label builders
# ─────────────────────────────────────────────────────────────────────────────

def _build_extractive_summary(article: dict) -> str:
    """
    Use mmr_sentences if present (stored by briefer.py), else fall back to
    the first two sentences from the sentences list.
    """
    mmr = article.get("mmr_sentences", [])
    if mmr:
        return " ||| ".join(str(s) for s in mmr)
    sents = article.get("sentences", [])
    fallback = sents[:2] if sents else []
    return " ||| ".join(str(s) for s in fallback)


def _primary_disruption_domain(domains) -> str:
    """
    Return the first (highest-scoring) entry in disruption_domains, or "none".
    Handles both list-of-str and list-of-dict shapes.
    """
    if not domains:
        return "none"
    first = domains[0]
    if isinstance(first, dict):
        return str(first.get("domain", first.get("name", "none")))
    return str(first)


def _label_article(article: dict) -> dict:
    """Convert a raw preprocessed article into a labelled corpus record."""
    title      = article.get("title", "") or ""
    clean_body = article.get("clean_body", "") or ""

    # ── Label 1 — industry ───────────────────────────────────────────────────
    industry_label = _classify_industry(title, clean_body)

    # ── Label 2 — disruption domain ──────────────────────────────────────────
    disruption_domain = _primary_disruption_domain(
        article.get("disruption_domains", [])
    )

    # ── Label 3 — risk regression target ─────────────────────────────────────
    raw_score = article.get("relevance_score", 0) or 0
    try:
        risk_score_norm = round(float(raw_score) / 100.0, 6)
    except (TypeError, ValueError):
        risk_score_norm = 0.0
    risk_score_norm = max(0.0, min(1.0, risk_score_norm))

    # ── Label 4 — extractive summary ─────────────────────────────────────────
    extractive_summary = _build_extractive_summary(article)

    # ── Label 5 — NER tags ───────────────────────────────────────────────────
    raw_entities = article.get("entities", []) or []
    ner_tags: list[dict] = []
    for ent in raw_entities:
        if isinstance(ent, dict):
            ner_tags.append({"text": ent.get("text", ""), "label": ent.get("label", "")})
        elif isinstance(ent, (list, tuple)) and len(ent) >= 2:
            ner_tags.append({"text": str(ent[0]), "label": str(ent[1])})

    # ── Label 6 — relevance binary ───────────────────────────────────────────
    impact = (article.get("impact_level") or "LOW").upper()
    is_relevant = 1 if impact in ("HIGH", "MEDIUM") else 0

    # ── Word count ───────────────────────────────────────────────────────────
    word_count = len(clean_body.split()) if clean_body else 0

    return {
        # Source fields
        "title":              title,
        "url":                article.get("url", "") or "",
        "published":          article.get("published", "") or "",
        "source":             article.get("source", "") or "",
        "trust_score":        float(article.get("trust_score", 0.5) or 0.5),

        # Labels
        "industry_label":     industry_label,
        "disruption_domain":  disruption_domain,
        "risk_score_norm":    risk_score_norm,
        "extractive_summary": extractive_summary,
        "ner_tags":           ner_tags,
        "is_relevant":        is_relevant,

        # Metadata
        "impact_level":       impact,
        "semantic_category":  article.get("semantic_category", "") or "",
        "score_breakdown":    article.get("score_breakdown", {}) or {},
        "cluster_id":         int(article.get("cluster_id", -1) if article.get("cluster_id") is not None else -1),
        "word_count":         word_count,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────────────

def export_corpus(run_id: str, runs_dir: str) -> CorpusExport:
    """
    Read data/runs/{run_id}_preprocessed.json and return a CorpusExport with
    all articles labelled and summary statistics populated.

    Raises FileNotFoundError if the run file does not exist.
    """
    # Sanitise run_id before building path (same logic as app.py /search)
    safe_id = "".join(c for c in run_id if c.isalnum() or c in ("_", "-"))
    fpath = os.path.join(runs_dir, f"{safe_id}_preprocessed.json")

    if not os.path.exists(fpath):
        raise FileNotFoundError(f"Run file not found: {fpath}")

    with open(fpath, "r", encoding="utf-8") as fh:
        run_data = json.load(fh)

    raw_articles: list[dict] = run_data.get("articles", [])

    labelled: list[dict] = [_label_article(a) for a in raw_articles]

    # ── Summary stats ─────────────────────────────────────────────────────────
    by_industry: dict[str, int] = Counter(a["industry_label"]     for a in labelled)
    by_domain:   dict[str, int] = Counter(a["disruption_domain"]  for a in labelled)
    by_impact:   dict[str, int] = Counter(a["impact_level"]       for a in labelled)

    total = len(labelled)
    relevant_count = sum(a["is_relevant"] for a in labelled)
    relevant_ratio = round(relevant_count / total, 4) if total else 0.0

    exported_at = datetime.now(timezone.utc).isoformat()

    return CorpusExport(
        articles       = labelled,
        run_id         = run_id,
        exported_at    = exported_at,
        total          = total,
        by_industry    = dict(by_industry),
        by_domain      = dict(by_domain),
        by_impact      = dict(by_impact),
        relevant_ratio = relevant_ratio,
    )


def write_jsonl(export: CorpusExport, output_path: str) -> str:
    """
    Write the labelled corpus to output_path as JSONL (one article per line).
    Overwrites any existing file at that path (idempotent re-export).
    Returns the resolved output_path.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        for article in export.articles:
            fh.write(json.dumps(article, ensure_ascii=False) + "\n")
    return output_path
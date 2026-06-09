"""
utils/briefer.py
─────────────────────────────────────────────────────────────────────────────
MMR sentence extraction + LLM abstractive intelligence brief generation
for supply chain event clusters.

Pipeline per cluster
────────────────────
  Step 1 — MMR (Maximal Marginal Relevance)
            Iteratively selects sentences from all cluster articles that
            are (a) relevant to the cluster centroid and (b) novel relative
            to sentences already selected.  Prevents three near-identical
            sentences being chosen when a unique critical fact exists.

  Step 2 — LLM Abstractive Brief
            The MMR sentence set + cluster metadata is passed to an LLM
            (via OpenRouter) with a structured prompt.  The LLM stitches
            the evidence into a fluent, structured intelligence brief.
            Output is a JSON dict with four fields:
              headline         — single-sentence event title
              what_happened    — 2-3 sentence factual summary
              affected_nodes   — list of supply chain nodes at risk
              outlook          — 1-2 sentence forward-looking assessment

LLM config (via .env)
─────────────────────
  OPENROUTER_API_KEY   — required for LLM brief generation
  BRIEFER_MODEL        — optional; defaults to meta-llama/llama-3.3-70b-instruct:free
  BRIEFER_MAX_TOKENS   — optional; default 400

MMR config (module-level constants)
─────────────────────────────────────
  MMR_LAMBDA           0.55  — balance relevance vs novelty (0=pure novelty, 1=pure relevance)
  MMR_MAX_SENTENCES    6     — max sentences fed to the LLM
  MMR_MIN_SENTENCE_LEN 40    — ignore very short sentences
  MMR_MAX_SENTENCE_LEN 300   — truncate runaway sentences

Public API
──────────
  extract_mmr_sentences(cluster)  → list[str]
      MMR-selected sentences from a cluster (no LLM required).

  generate_brief(cluster)  → dict
      Full intelligence brief dict.  Falls back to LexRank summary
      string if LLM unavailable.

  attach_briefs(clusters)  → list[dict]  (mutates in-place, returns same list)
      Convenience: enrich every cluster with 'brief' and 'mmr_sentences' fields.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Optional

import numpy as np
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────

MMR_LAMBDA        = 0.55   # relevance weight  (1-MMR_LAMBDA = novelty weight)
MMR_MAX_SENTENCES = 6      # sentences fed to LLM prompt
MMR_MIN_SENT_LEN  = 40
MMR_MAX_SENT_LEN  = 300

_OPENROUTER_URL  = "https://openrouter.ai/api/v1/chat/completions"
_API_KEY         = os.getenv("OPENROUTER_API_KEY", "")
_MODEL           = os.getenv("BRIEFER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
_MAX_TOKENS      = int(os.getenv("BRIEFER_MAX_TOKENS", "400"))
_REQUEST_TIMEOUT = 30

# ──────────────────────────────────────────────────────────────────────────────
# MMR CORE
# ──────────────────────────────────────────────────────────────────────────────

def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two 1-D vectors (already L2-normalised)."""
    return float(np.dot(a, b))


def _cosine_sim_to_set(vec: np.ndarray, vecs: list[np.ndarray]) -> float:
    """Max cosine similarity between vec and any vector in vecs."""
    if not vecs:
        return 0.0
    return max(_cosine_sim(vec, v) for v in vecs)


def extract_mmr_sentences(
    cluster: dict,
    n:       int   = MMR_MAX_SENTENCES,
    lam:     float = MMR_LAMBDA,
) -> list[str]:
    """
    Select up to *n* sentences from all articles in *cluster* using MMR.

    The centroid is the mean of all available sentence embeddings.  If no
    sentence embeddings are available, falls back to returning the first
    *n* sentences from the LexRank summary string.

    Parameters
    ──────────
    cluster  Cluster dict from event_clusterer (articles list inside).
    n        Max sentences to return.
    lam      Trade-off: higher → more relevant, lower → more novel.

    Returns
    ───────
    List of selected sentence strings, ordered by MMR selection priority.
    """
    articles = cluster.get("articles", [])

    # ── Collect (sentence, embedding) pairs across all articles ──────────────
    sent_texts:  list[str]        = []
    sent_embeds: list[np.ndarray] = []

    for art in articles:
        sents  = art.get("sentences", [])
        embeds = art.get("sentence_embeddings")  # may be absent

        for i, sent in enumerate(sents):
            text = sent.strip()
            if len(text) < MMR_MIN_SENT_LEN:
                continue
            if len(text) > MMR_MAX_SENT_LEN:
                text = text[:MMR_MAX_SENT_LEN].rsplit(" ", 1)[0] + "…"

            emb = None
            if embeds is not None and i < len(embeds):
                e = np.array(embeds[i], dtype=np.float32)
                norm = np.linalg.norm(e)
                if norm > 0:
                    emb = e / norm

            sent_texts.append(text)
            sent_embeds.append(emb)

    if not sent_texts:
        # Fallback: split the existing LexRank summary
        raw = cluster.get("summary", "")
        fallback_sents = [s.strip() for s in re.split(r"\.\s+", raw) if len(s.strip()) >= MMR_MIN_SENT_LEN]
        return fallback_sents[:n]

    # ── If no sentence embeddings available, just deduplicate greedily ───────
    if all(e is None for e in sent_embeds):
        seen: set[str] = set()
        result: list[str] = []
        for s in sent_texts:
            key = s.lower()[:80]
            if key not in seen:
                seen.add(key)
                result.append(s)
            if len(result) >= n:
                break
        return result

    # ── Build cluster centroid from doc embeddings ────────────────────────────
    doc_embs = []
    for art in articles:
        emb = art.get("doc_embedding") or art.get("embedding")
        if emb is not None:
            e = np.array(emb, dtype=np.float32)
            norm = np.linalg.norm(e)
            if norm > 0:
                doc_embs.append(e / norm)

    if doc_embs:
        centroid = np.mean(doc_embs, axis=0)
        c_norm   = np.linalg.norm(centroid)
        if c_norm > 0:
            centroid /= c_norm
    else:
        # Use mean of sentence embeddings as centroid
        valid = [e for e in sent_embeds if e is not None]
        if not valid:
            return sent_texts[:n]
        centroid = np.mean(valid, axis=0)
        c_norm   = np.linalg.norm(centroid)
        if c_norm > 0:
            centroid /= c_norm

    # ── MMR greedy selection ─────────────────────────────────────────────────
    selected_texts:  list[str]        = []
    selected_embeds: list[np.ndarray] = []
    remaining_idx = list(range(len(sent_texts)))

    for _ in range(min(n, len(sent_texts))):
        best_idx   = -1
        best_score = -2.0

        for i in remaining_idx:
            emb = sent_embeds[i]
            if emb is None:
                rel = 0.0
            else:
                rel = _cosine_sim(emb, centroid)

            red = _cosine_sim_to_set(emb, selected_embeds) if emb is not None else 0.0

            score = lam * rel - (1.0 - lam) * red
            if score > best_score:
                best_score = score
                best_idx   = i

        if best_idx == -1:
            break

        selected_texts.append(sent_texts[best_idx])
        if sent_embeds[best_idx] is not None:
            selected_embeds.append(sent_embeds[best_idx])
        remaining_idx.remove(best_idx)

    return selected_texts


# ──────────────────────────────────────────────────────────────────────────────
# LLM BRIEF GENERATION
# ──────────────────────────────────────────────────────────────────────────────

_BRIEF_SYSTEM = (
    "You are an expert supply chain risk analyst. "
    "You write concise, factual intelligence briefs from news evidence. "
    "Never invent facts not present in the evidence. "
    "Respond ONLY with a valid JSON object — no markdown, no preamble."
)

_BRIEF_USER_TMPL = """\
You are analysing a supply chain disruption event cluster.

CLUSTER METADATA
────────────────
Impact level  : {impact_level}
Risk score    : {risk_score}/100
Linked nodes  : {linked_nodes}
Sources       : {sources}
Article count : {article_count}

EVIDENCE SENTENCES (extracted by MMR — most relevant and novel facts)
──────────────────────────────────────────────────────────────────────
{evidence}

TASK
────
Write a structured intelligence brief as a JSON object with EXACTLY these four keys:

  "headline"       – One crisp sentence naming the event and the affected entity/region.
  "what_happened"  – 2-3 sentences summarising the confirmed facts from the evidence.
  "affected_nodes" – JSON array of supply chain node names at risk (from Linked nodes and evidence).
  "outlook"        – 1-2 sentences on the likely near-term impact or escalation risk.

Output ONLY the JSON object. No markdown fences. No extra keys. No commentary."""


def _call_llm(prompt: str) -> Optional[str]:
    """
    Send a prompt to OpenRouter and return the raw text response.
    Returns None on any failure.
    """
    if not _API_KEY:
        logger.warning("OPENROUTER_API_KEY not set — skipping LLM brief generation.")
        return None

    payload = {
        "model": _MODEL,
        "max_tokens": _MAX_TOKENS,
        "messages": [
            {"role": "system", "content": _BRIEF_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        "transforms": ["middle-out"],
    }

    try:
        resp = requests.post(
            _OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {_API_KEY}",
                "Content-Type":  "application/json",
                "HTTP-Referer":  "supply-chain-intelligence",
            },
            json=payload,
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning(f"LLM brief: HTTP {resp.status_code} — {resp.text[:200]}")
            return None

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            logger.warning("LLM brief: empty choices in response")
            return None

        return choices[0].get("message", {}).get("content", "").strip()

    except requests.exceptions.Timeout:
        logger.warning("LLM brief: request timed out.")
        return None
    except Exception as e:
        logger.warning(f"LLM brief: unexpected error — {e}")
        return None


def _parse_brief(raw: str, cluster: dict, mmr_sents: list[str]) -> dict:
    """
    Parse LLM JSON output into a validated brief dict.
    Falls back gracefully if parsing fails.
    """
    # Strip residual markdown fences if model added them
    clean = re.sub(r"```(?:json)?|```", "", raw).strip()
    # Extract first {...} block
    match = re.search(r"\{.*\}", clean, re.DOTALL)
    if match:
        clean = match.group(0)

    try:
        parsed = json.loads(clean)
        return {
            "headline":       str(parsed.get("headline",       "")).strip(),
            "what_happened":  str(parsed.get("what_happened",  "")).strip(),
            "affected_nodes": parsed.get("affected_nodes", []) if isinstance(parsed.get("affected_nodes"), list) else [],
            "outlook":        str(parsed.get("outlook",        "")).strip(),
            "source":         "llm",
            "model":          _MODEL,
            "mmr_sentence_count": len(mmr_sents),
        }
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"LLM brief JSON parse failed ({e}) — using fallback.")
        return _fallback_brief(cluster, mmr_sents)


def _fallback_brief(cluster: dict, mmr_sents: list[str]) -> dict:
    """
    Construct a best-effort brief without an LLM using MMR sentences
    and cluster metadata.
    """
    articles = cluster.get("articles", [])
    headline = ""
    if articles:
        headline = articles[0].get("clean_title") or articles[0].get("title", "")

    what_happened = "  ".join(mmr_sents[:3]) if mmr_sents else cluster.get("summary", "")

    nodes = cluster.get("linked_nodes", [])
    affected = []
    for node in nodes:
        ci = node.find(":")
        affected.append(node[ci + 1:] if ci > -1 else node)

    return {
        "headline":           headline,
        "what_happened":      what_happened,
        "affected_nodes":     affected,
        "outlook":            "",
        "source":             "fallback",
        "model":              None,
        "mmr_sentence_count": len(mmr_sents),
    }


def generate_brief(cluster: dict) -> dict:
    """
    Generate an intelligence brief for a single cluster.

    Steps:
      1. Run MMR to extract key sentences.
      2. Build LLM prompt from evidence + metadata.
      3. Call LLM (OpenRouter).
      4. Parse and validate response.
      5. Return brief dict (falls back gracefully if LLM unavailable).

    Parameters
    ──────────
    cluster   Cluster dict from event_clusterer, already enriched with
              sentence embeddings from sbert_encoder.

    Returns
    ───────
    {
        "headline":           str,
        "what_happened":      str,
        "affected_nodes":     list[str],
        "outlook":            str,
        "source":             "llm" | "fallback",
        "model":              str | None,
        "mmr_sentence_count": int,
    }
    """
    mmr_sents = extract_mmr_sentences(cluster)

    if not _API_KEY:
        return _fallback_brief(cluster, mmr_sents)

    # Format linked_nodes for the prompt
    nodes = cluster.get("linked_nodes", [])
    node_display = ", ".join(
        n.split(":", 1)[1] if ":" in n else n for n in nodes[:8]
    ) or "—"

    sources = ", ".join(cluster.get("sources", [])[:5]) or "—"

    evidence_lines = "\n".join(
        f"  [{i+1}] {s}" for i, s in enumerate(mmr_sents)
    )

    prompt = _BRIEF_USER_TMPL.format(
        impact_level  = cluster.get("impact_level", "LOW"),
        risk_score    = cluster.get("risk_score",   0),
        linked_nodes  = node_display,
        sources       = sources,
        article_count = cluster.get("article_count", 1),
        evidence      = evidence_lines or "  (no sentences extracted)",
    )

    raw = _call_llm(prompt)
    if not raw:
        return _fallback_brief(cluster, mmr_sents)

    return _parse_brief(raw, cluster, mmr_sents)


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC CONVENIENCE
# ──────────────────────────────────────────────────────────────────────────────

def attach_briefs(
    clusters:       list[dict],
    only_real:      bool  = True,
    min_articles:   int   = 2,
    delay_s:        float = 0.3,
) -> list[dict]:
    """
    Enrich each qualifying cluster dict with:
      - "brief"          → intelligence brief dict
      - "mmr_sentences"  → raw MMR-selected sentence list

    Parameters
    ──────────
    clusters       Cluster list from event_clusterer / attach_summaries.
    only_real      Skip noise singletons (is_noise=True).
    min_articles   Skip clusters smaller than this.
    delay_s        Polite delay between LLM calls (seconds).

    Returns the same list (mutated in-place).
    """
    briefed = 0
    skipped = 0

    for cluster in clusters:
        # Skip noise / tiny clusters unless they're the only ones
        if only_real and cluster.get("is_noise", False):
            cluster["brief"]         = _fallback_brief(cluster, [])
            cluster["mmr_sentences"] = []
            skipped += 1
            continue

        if cluster.get("article_count", 0) < min_articles:
            cluster["brief"]         = _fallback_brief(cluster, [])
            cluster["mmr_sentences"] = []
            skipped += 1
            continue

        mmr_sents = extract_mmr_sentences(cluster)
        cluster["mmr_sentences"] = mmr_sents

        try:
            cluster["brief"] = generate_brief(cluster)
            briefed += 1
            if delay_s > 0 and briefed < len(clusters):
                time.sleep(delay_s)
        except Exception as e:
            logger.warning(f"Brief generation failed for cluster {cluster.get('cluster_id')}: {e}")
            cluster["brief"] = _fallback_brief(cluster, mmr_sents)
            skipped += 1

    logger.info(
        f"attach_briefs: {briefed} LLM brief(s) generated, "
        f"{skipped} fallback(s) — {len(clusters)} total clusters"
    )
    return clusters
"""
utils/article_preprocessor.py
==============================
NER-based article preprocessing pipeline for the Supply Chain
Disruption Intelligence System.

This module sits between relevance_scorer.py and Sentence-BERT
embedding/clustering so that:
  1. Raw article text is cleaned and normalised.
  2. Named Entities (ORG, GPE, PRODUCT, EVENT, NORP, FAC) are
     extracted via spaCy and fused with exposure-map entities.
  3. Each article gets a structured `nlp_payload` dict that can be
     passed directly to a Sentence-BERT encoder.

Pipeline stages
---------------
  Stage 1  — Text cleaning
             • Strip HTML tags / entities
             • Normalise unicode (NFKC)
             • Collapse whitespace, fix smart-quotes
             • Remove boilerplate phrases (bylines, timestamps, cookie notices)
             • Strip URLs, tracking suffixes

  Stage 2  — Sentence segmentation
             • spaCy sentence boundary detection
             • Drop sentences shorter than MIN_SENT_CHARS (low-signal)
             • Cap total text at MAX_TOKENS_PER_ARTICLE

  Stage 3  — NER tagging
             • spaCy en_core_web_sm (fast, no heavy deps)
             • Entity types kept: ORG, GPE, LOC, PRODUCT, FAC, EVENT, NORP
             • De-dup and normalise entity surface forms
             • Fuse with matched_entities from relevance_scorer (high precision)

  Stage 4  — Sentence-BERT payload assembly
             • Canonical "input_text" for embedding
               = "[TITLE] <title>  [BODY] <clean body>"
             • Entity-enriched metadata attached separately
             • Impact-level and score carried through for downstream
               label-guided training / fine-tuning

Public API
----------
  preprocess_articles(articles, exposure)
      Accepts the list returned by score_articles() (each already has
      relevance_score, impact_level, matched_entities, linked_nodes).
      Returns a list of PreprocessedArticle dicts ready for embedding.

  preprocess_for_sbert(articles, exposure)
      Convenience wrapper — returns only the input_text strings and
      metadata needed by sentence_transformers SentenceTransformer.encode().

Configuration (module-level constants)
---------------------------------------
  MIN_SENT_CHARS       = 40     Minimum chars for a sentence to be kept
  MAX_SENTENCES        = 12     Max sentences per article body
  MAX_TOKENS_PER_ARTICLE = 384  Soft token cap (SBERT max is 512)
  NER_BATCH_SIZE       = 32     spaCy pipe batch size
  SPACY_MODEL          = "en_core_web_sm"
"""

import html
import logging
import re
import unicodedata
from typing import Optional

logger = logging.getLogger(__name__)

# ==========================================
# CONFIG
# ==========================================

MIN_SENT_CHARS         = 40
MAX_SENTENCES          = 12
MAX_TOKENS_PER_ARTICLE = 384    # conservative to stay under SBERT 512
NER_BATCH_SIZE         = 32
SPACY_MODEL            = "en_core_web_sm"

# Entity types we care about for supply chain NER
_SC_ENT_TYPES = {
    "ORG",      # companies, agencies, institutions
    "GPE",      # geopolitical entities (countries, cities, states)
    "LOC",      # natural locations (seas, straits)
    "FAC",      # facilities (ports, airports, plants)
    "PRODUCT",  # products, commodities
    "EVENT",    # named events (strikes, conflicts)
    "NORP",     # nationalities, political groups
}

# Boilerplate patterns to strip before NER
_BOILERPLATE_PATTERNS = [
    r"(?i)subscribe\s+to\s+our\s+newsletter.*",
    r"(?i)click\s+here\s+to\s+(read|view|subscribe).*",
    r"(?i)copyright\s+©?\s*\d{4}.*",
    r"(?i)all\s+rights\s+reserved.*",
    r"(?i)this\s+article\s+(originally\s+)?appeared.*",
    r"(?i)read\s+more\s*:.*",
    r"(?i)related\s+articles?\s*:.*",
    r"(?i)advertisement\s*",
    r"(?i)sponsored\s+content\s*",
    r"(?i)\bvia\s+(reuters|ap|afp|bloomberg)\b.*?(?=\.|$)",
    r"https?://\S+",                    # URLs
    r"\[\+\d+\s+chars\]",              # NewsAPI content truncation marker
    r"(?m)^\s*by\s+[A-Z][a-z]+\s+[A-Z][a-z]+\s*$",  # Byline "By John Smith"
    r"(?m)^\s*\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}\s*$",  # standalone dates
    r"<[^>]+>",                         # residual HTML tags
    r"&[a-zA-Z]{2,6};",                # HTML entities
]

_BOILERPLATE_RE = re.compile(
    "|".join(f"(?:{p})" for p in _BOILERPLATE_PATTERNS),
    flags=re.MULTILINE | re.DOTALL
)

# Smart-quote normalisation map
_SMART_QUOTES = str.maketrans({
    "\u2018": "'",  "\u2019": "'",
    "\u201c": '"',  "\u201d": '"',
    "\u2013": "-",  "\u2014": "-",
    "\u00a0": " ",  "\u2026": "...",
})

# ==========================================
# LAZY SPACY LOAD
# ==========================================

_nlp = None


def _get_nlp():
    """
    Load spaCy model once. Falls back gracefully if not installed so
    the rest of the pipeline can run without NER.
    """
    global _nlp
    if _nlp is not None:
        return _nlp

    try:
        import spacy
        try:
            _nlp = spacy.load(SPACY_MODEL, disable=["parser", "lemmatizer"])
            # Ensure sentencizer is present (senter is lighter than parser)
            if "senter" not in _nlp.pipe_names and "sentencizer" not in _nlp.pipe_names:
                _nlp.add_pipe("sentencizer")
            logger.info(f"spaCy model '{SPACY_MODEL}' loaded.")
        except OSError:
            logger.warning(
                f"spaCy model '{SPACY_MODEL}' not found. "
                f"Run:  python -m spacy download {SPACY_MODEL}\n"
                "Falling back to regex sentence splitter."
            )
            _nlp = None
    except ImportError:
        logger.warning(
            "spaCy not installed. Run:  pip install spacy\n"
            "Falling back to regex sentence splitter."
        )
        _nlp = None

    return _nlp


# ==========================================
# STAGE 1 — TEXT CLEANING
# ==========================================

def _clean_text(raw: str) -> str:
    """
    Return a clean, normalised version of raw article text.

    Steps:
      1. Decode HTML entities (e.g. &amp; → &)
      2. Unicode NFKC normalisation (full-width chars, ligatures, etc.)
      3. Smart-quote substitution
      4. Strip boilerplate patterns (bylines, URLs, copyright, etc.)
      5. Collapse runs of whitespace / blank lines
    """
    if not raw:
        return ""

    # 1. HTML entity decode
    text = html.unescape(raw)

    # 2. Unicode normalisation
    text = unicodedata.normalize("NFKC", text)

    # 3. Smart quotes / dashes
    text = text.translate(_SMART_QUOTES)

    # 4. Boilerplate strip
    text = _BOILERPLATE_RE.sub(" ", text)

    # 5. Whitespace normalisation
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


# ==========================================
# STAGE 2 — SENTENCE SEGMENTATION
# ==========================================

def _regex_sent_split(text: str) -> list[str]:
    """
    Simple regex sentence splitter used as fallback when spaCy
    is unavailable. Splits on [.!?] followed by whitespace + capital.
    """
    raw_sents = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    return [s.strip() for s in raw_sents if s.strip()]


def _segment_sentences(text: str) -> list[str]:
    """
    Return a list of sentences from cleaned text.
    Filters out sentences shorter than MIN_SENT_CHARS.
    Caps output at MAX_SENTENCES.
    """
    nlp = _get_nlp()

    if nlp is not None:
        doc   = nlp(text[:10_000])  # safety ceiling for very long text
        sents = [s.text.strip() for s in doc.sents]
    else:
        sents = _regex_sent_split(text)

    # Filter short / noise sentences
    sents = [s for s in sents if len(s) >= MIN_SENT_CHARS]

    return sents[:MAX_SENTENCES]


# ==========================================
# STAGE 3 — NER TAGGING
# ==========================================

def _extract_entities_spacy(text: str) -> list[dict]:
    """
    Run spaCy NER over text and return entity dicts:
    [{"text": "TSMC", "label": "ORG", "start": 12, "end": 16}, ...]
    """
    nlp = _get_nlp()
    if nlp is None:
        return []

    doc     = nlp(text[:10_000])
    seen    = set()
    results = []

    for ent in doc.ents:
        if ent.label_ not in _SC_ENT_TYPES:
            continue
        norm = ent.text.strip()
        if not norm or len(norm) < 2:
            continue
        key = (norm.lower(), ent.label_)
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "text":  norm,
            "label": ent.label_,
        })

    return results


def _normalise_entity_text(raw: str) -> str:
    """
    Light normalisation of entity surface forms:
      - Strip possessives ("TSMC's" → "TSMC")
      - Remove leading articles ("The Red Sea" → "Red Sea")
      - Title-case for GPE/LOC (some models return all-caps)
    """
    norm = raw.strip()
    norm = re.sub(r"'s$", "", norm)
    norm = re.sub(r"^(the|a|an)\s+", "", norm, flags=re.IGNORECASE)
    return norm.strip()


def _fuse_entities(
    spacy_ents: list[dict],
    rule_matched: list[str],
    exposure: dict,
) -> list[dict]:
    """
    Merge spaCy-extracted entities with rule-based matched_entities from
    the relevance scorer.

    Rule-matched entities are tagged with their node type (supplier,
    material, port, route) for downstream use.  spaCy entities not
    already present add breadth (novel mentions in text).

    Returns a deduplicated list of entity dicts:
    {
        "text":   str,          # surface form
        "label":  str,          # NER label or "RULE" for rule-matched
        "source": str,          # "spacy" | "rule"
        "node_type": str | None # supplier | material | port | route | None
    }
    """
    supplier_set = set(s.lower() for s in exposure.get("suppliers",  []))
    material_set = set(m.lower() for m in exposure.get("materials",  []))
    port_set     = set(p.lower() for p in exposure.get("ports",      []))
    route_set    = set(r.lower() for r in exposure.get("routes",     []))

    def _node_type(name: str) -> Optional[str]:
        n = name.lower()
        if n in supplier_set: return "supplier"
        if n in material_set: return "material"
        if n in port_set:     return "port"
        if n in route_set:    return "route"
        return None

    fused = []
    seen  = set()

    # First: rule-matched (high precision — keep first)
    for name in rule_matched:
        norm = _normalise_entity_text(name)
        key  = norm.lower()
        if key in seen:
            continue
        seen.add(key)
        fused.append({
            "text":      norm,
            "label":     "RULE",
            "source":    "rule",
            "node_type": _node_type(norm),
        })

    # Second: spaCy additions
    for ent in spacy_ents:
        norm = _normalise_entity_text(ent["text"])
        key  = norm.lower()
        if key in seen:
            continue
        seen.add(key)
        fused.append({
            "text":      norm,
            "label":     ent["label"],
            "source":    "spacy",
            "node_type": _node_type(norm),
        })

    return fused


# ==========================================
# STAGE 4 — SBERT PAYLOAD ASSEMBLY
# ==========================================

_TOKEN_ESTIMATE_RATIO = 0.75   # rough chars-per-token estimate for English


def _build_input_text(title: str, sentences: list[str]) -> str:
    """
    Build the canonical SBERT input string:

      [TITLE] <title text>  [BODY] <sentence 1>  <sentence 2>  ...

    Truncated to keep estimated token count under MAX_TOKENS_PER_ARTICLE.
    """
    max_body_chars = int(MAX_TOKENS_PER_ARTICLE / _TOKEN_ESTIMATE_RATIO)

    body = "  ".join(sentences)

    # Truncate body if needed
    if len(body) > max_body_chars:
        body = body[:max_body_chars].rsplit(" ", 1)[0] + "..."

    return f"[TITLE] {title.strip()}  [BODY] {body}"


def _build_entity_string(entities: list[dict]) -> str:
    """
    Build a compact entity context string for optional prepending
    to SBERT input (for entity-augmented models):

      [ENTITIES] TSMC (ORG) | Taiwan (GPE) | semiconductors (PRODUCT)
    """
    parts = [f"{e['text']} ({e['label']})" for e in entities[:10]]
    if not parts:
        return ""
    return "[ENTITIES] " + " | ".join(parts)


# ==========================================
# PUBLIC: preprocess_articles
# ==========================================

def preprocess_articles(
    articles: list[dict],
    exposure: dict,
) -> list[dict]:
    """
    Full NER-based preprocessing pipeline over a list of scored articles.

    Each output dict extends the input article with:
    ─────────────────────────────────────────────────────────────────
    clean_title       str       Cleaned title text
    clean_body        str       Cleaned body (boilerplate stripped)
    sentences         list[str] Segmented, filtered sentences
    ner_entities      list[dict] Fused rule + spaCy entities
    entity_string     str       Compact entity context string
    input_text        str       Canonical SBERT input: [TITLE]+[BODY]
    input_text_w_ent  str       Entity-augmented SBERT input (optional)
    token_estimate    int       Estimated token count of input_text
    preprocessing_ok  bool      False if an error occurred for this article
    ─────────────────────────────────────────────────────────────────
    """
    processed = []

    for article in articles:
        try:
            # --- Gather raw text ---
            raw_title = article.get("title",   "") or ""
            raw_body  = (
                article.get("summary",     "")
                or article.get("description", "")
                or ""
            )

            # Stage 1 — Clean
            clean_title = _clean_text(raw_title)
            clean_body  = _clean_text(raw_body)

            # Stage 2 — Segment
            sentences = _segment_sentences(clean_body) if clean_body else []

            # Stage 3 — NER
            full_text  = f"{clean_title}. {clean_body}"
            spacy_ents = _extract_entities_spacy(full_text)
            rule_ents  = article.get("matched_entities", [])
            ner_ents   = _fuse_entities(spacy_ents, rule_ents, exposure)

            # Stage 4 — SBERT payload
            input_text       = _build_input_text(clean_title, sentences)
            entity_string    = _build_entity_string(ner_ents)
            input_text_w_ent = (
                f"{entity_string}  {input_text}" if entity_string else input_text
            )
            token_estimate   = int(len(input_text) * _TOKEN_ESTIMATE_RATIO)

            enriched = dict(article)
            enriched.update({
                "clean_title":       clean_title,
                "clean_body":        clean_body,
                "sentences":         sentences,
                "ner_entities":      ner_ents,
                "entity_string":     entity_string,
                "input_text":        input_text,
                "input_text_w_ent":  input_text_w_ent,
                "token_estimate":    token_estimate,
                "preprocessing_ok":  True,
            })

            processed.append(enriched)

        except Exception as e:
            logger.warning(
                f"Preprocessing error for article '{article.get('title','?')[:60]}': {e}"
            )
            fallback = dict(article)
            fallback.update({
                "clean_title":       article.get("title",   "") or "",
                "clean_body":        article.get("summary", "") or "",
                "sentences":         [],
                "ner_entities":      [],
                "entity_string":     "",
                "input_text":        article.get("title",   "") or "",
                "input_text_w_ent":  article.get("title",   "") or "",
                "token_estimate":    0,
                "preprocessing_ok":  False,
            })
            processed.append(fallback)

    ok_count  = sum(1 for a in processed if a["preprocessing_ok"])
    ent_count = sum(len(a["ner_entities"]) for a in processed)

    logger.info(
        f"Preprocessed {len(processed)} articles — "
        f"ok={ok_count} "
        f"total_entities={ent_count} "
        f"avg_entities={round(ent_count/max(len(processed),1),1)}"
    )

    return processed


# ==========================================
# PUBLIC: preprocess_for_sbert
# ==========================================

def preprocess_for_sbert(
    articles: list[dict],
    exposure: dict,
    use_entity_augmented: bool = False,
) -> dict:
    """
    Convenience wrapper.  Returns:
    {
        "texts":     list[str]   — input strings for SentenceTransformer.encode()
        "metadata":  list[dict]  — parallel metadata list for each text
        "articles":  list[dict]  — full preprocessed article dicts
    }

    Parameters
    ----------
    articles             : list of scored article dicts from score_articles()
    exposure             : exposure map from build_exposure_map()
    use_entity_augmented : if True, uses input_text_w_ent (entity prefix)
                           instead of plain input_text
    """
    preprocessed = preprocess_articles(articles, exposure)

    text_key = "input_text_w_ent" if use_entity_augmented else "input_text"

    texts    = [a[text_key] for a in preprocessed]
    metadata = [
        {
            "title":          a.get("clean_title", ""),
            "url":            a.get("url", ""),
            "impact_level":   a.get("impact_level", "LOW"),
            "relevance_score": a.get("relevance_score", 0),
            "source":         a.get("source", ""),
            "published":      a.get("published", ""),
            "ner_entities":   a.get("ner_entities", []),
            "linked_nodes":   a.get("linked_nodes", []),
            "token_estimate": a.get("token_estimate", 0),
        }
        for a in preprocessed
    ]

    return {
        "texts":    texts,
        "metadata": metadata,
        "articles": preprocessed,
    }


# ==========================================
# QUICK SELF-TEST
# (python -m utils.article_preprocessor)
# ==========================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    dummy_exposure = {
        "suppliers":  ["TSMC", "Samsung"],
        "materials":  ["semiconductors", "lithium"],
        "ports":      ["Port of Kaohsiung"],
        "routes":     ["Taiwan Strait"],
        "countries":  ["Taiwan", "South Korea"],
        "cities":     {"Taiwan": ["Taipei", "Kaohsiung"]},
        "material_records": {},
        "port_records":     {},
        "route_records":    {},
    }

    dummy_articles = [
        {
            "title":   "TSMC halts production at Kaohsiung fab after earthquake",
            "summary": (
                "Taiwan Semiconductor Manufacturing Company (TSMC) has suspended "
                "operations at its Kaohsiung fabrication plant following a 6.4 "
                "magnitude earthquake near the Taiwan Strait. The disruption is "
                "expected to affect Q2 chip shipments to major OEM partners. "
                "Supply chain analysts warn of a 3-4 week lead time extension for "
                "advanced node wafers. Port of Kaohsiung container throughput is "
                "also impacted by aftershocks. Click here to subscribe. &copy; 2024"
            ),
            "url":           "https://example.com/tsmc-earthquake",
            "published":     "2024-04-03T09:00:00Z",
            "source":        "FreightWaves",
            "trust_score":   0.92,
            "impact_level":  "HIGH",
            "relevance_score": 82,
            "matched_entities": ["TSMC", "Port of Kaohsiung", "Taiwan Strait"],
            "linked_nodes":  ["supplier:TSMC", "port:Port of Kaohsiung"],
        },
        {
            "title":   "Lithium prices surge amid Chilean miner strike",
            "summary": (
                "Spot prices for lithium carbonate have jumped 12% after workers "
                "at Albemarle's Atacama operations walked out over wage disputes. "
                "The Chilean labour action threatens to cut South American lithium "
                "output by an estimated 8% in Q3. Battery manufacturers are "
                "scrambling to secure alternative supply from Australian producers."
            ),
            "url":           "https://example.com/lithium-strike",
            "published":     "2024-04-02T14:30:00Z",
            "source":        "Mining.com",
            "trust_score":   0.85,
            "impact_level":  "MEDIUM",
            "relevance_score": 58,
            "matched_entities": ["lithium"],
            "linked_nodes":  ["material:lithium"],
        },
    ]

    result = preprocess_for_sbert(dummy_articles, dummy_exposure)

    print("\n" + "═" * 60)
    print("  SBERT PREPROCESSING SELF-TEST")
    print("═" * 60)

    for i, (text, meta) in enumerate(zip(result["texts"], result["metadata"])):
        art = result["articles"][i]
        print(f"\n── Article {i+1}: {meta['title'][:55]}...")
        print(f"   Impact     : {meta['impact_level']} ({meta['relevance_score']}/100)")
        print(f"   Tokens est.: {meta['token_estimate']}")
        print(f"   Entities   : {[e['text'] for e in meta['ner_entities']]}")
        print(f"   Sentences  : {len(art['sentences'])}")
        print(f"   Input text :")
        print(f"     {text[:200]}{'...' if len(text) > 200 else ''}")
        print(f"   Entity str : {art['entity_string']}")
        print()

    print("═" * 60)
    print(f"  Total articles : {len(result['articles'])}")
    print(f"  Total texts    : {len(result['texts'])}")
    print("═" * 60 + "\n")
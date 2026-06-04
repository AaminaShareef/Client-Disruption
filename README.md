# Supply Chain Risk Intelligence — Backend

## Quick Start

```bash
# 1. Install dependencies (Python 3.10+)
pip install -r requirements.txt

# 2. Place index.html in the same directory as app.py

# 3. Run the server
python app.py
# → http://localhost:5000
```

## Environment Variables (all optional)

| Variable       | Default | Description                            |
|----------------|---------|----------------------------------------|
| `PORT`         | `5000`  | HTTP port to listen on                 |
| `FLASK_DEBUG`  | `false` | Set `true` for auto-reload             |
| `RSS_TIMEOUT`  | `8`     | Per-feed fetch timeout (seconds)       |
| `RSS_WORKERS`  | `12`    | Parallel RSS fetch threads             |
| `MAX_ARTICLES` | `50`    | Max articles returned per analysis     |

## Architecture

```
POST /analyze
  │
  ├─ build_queries()        → extract entity terms from profile JSON
  ├─ fetch_rss_articles()   → parallel fetch 20+ RSS feeds via feedparser
  ├─ match_disruptions()    → score & filter articles per entity match
  │     ├─ calculate_relevance()  → entity match + disruption keywords + recency
  │     └─ _determine_impact()   → CRITICAL / HIGH / MEDIUM / LOW
  ├─ calculate_risk()       → weighted score → overall risk level
  ├─ query_breakdown()      → per-category article counts
  └─ generate_summary()     → human-readable risk message
```

## Scoring Logic

**Relevance score (per article)**
- +10 per entity query term found in title/description
- +3  per disruption-lexicon keyword hit
- +5  if feed category matches article's disruption category
- +8/4/1 recency boost (1d / 7d / 30d)

**Risk level thresholds (raw_score)**
- ≥ 60 → CRITICAL
- ≥ 30 → HIGH
- ≥ 10 → MEDIUM
- < 10 → LOW

## RSS Feeds Included (all free, no API key)

| Feed                  | Category     |
|-----------------------|--------------|
| Reuters World/Business| geopolitical |
| BBC Business          | supplier     |
| AP Top News           | geopolitical |
| FreightWaves          | logistics    |
| SupplyChainDive       | logistics    |
| Logistics Management  | logistics    |
| DC Velocity           | logistics    |
| Supply Chain 24/7     | logistics    |
| Maritime Executive    | logistics    |
| Lloyd's List          | logistics    |
| Splash247             | logistics    |
| Mining.com            | materials    |
| OilPrice.com          | materials    |
| Metal Bulletin        | materials    |
| AgriBusinessGlobal    | materials    |
| Fastmarkets           | materials    |
| Semiconductor Eng.    | supplier     |
| EE Times              | supplier     |
| ElectronicsWeekly     | supplier     |
| Trade Finance Global  | geopolitical |
| Global Trade Review   | geopolitical |
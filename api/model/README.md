# Seam custom model: getting started

Status, rules and history:
- **STATUS.md**: what's in progress, what's next, what's done. Start here.
- **LOG.md**: what happened in each session, newest first.
- **AGENTS.md**: the documentation rules every session follows.
- **RESEARCH.md**: why we're doing this and which options we considered.

## Catching up an agent
Paste this:
> Read api/model/AGENTS.md and follow it. Then summarise STATUS.md and the latest LOG.md entries, and tell me what you'd do next.

## Setup
- **Prod data (verified 2026-10-28):** log into the prod site as an `ADMIN_EMAILS` user, open `/admin`, export, and save it as `data/models/snapshots/items-<date>.jsonl`. Items table only, 10 exports per 15 min. Run `python3 api/model/queries/h1_jsonl.py <file>` for H1. There's no direct DB access.
- Old local snapshot: `data/seam.db` (SQLite, 2026-10-18, 1,107 tagged items, before Depop and the `leather` query). Queries for it are in `queries/`.
- Training box: Caden's PC (RTX 3080 Ti, 12 GB) under WSL2 (RESEARCH.md §7).
- Data and weights go in `data/models/` (gitignored).

## Step 1: is the inventory leather-heavy? (H1)
On an export: `python3 api/model/queries/h1_jsonl.py <file>`. On a Postgres you can reach:
```sql
SELECT source, slot,
       count(*) AS items,
       round(100.0 * avg((tags->>'material' ILIKE '%leather%' OR category = 'leather_jacket')::int), 1) AS leather_pct
FROM items
WHERE status = 'active' AND tags IS NOT NULL
GROUP BY ROLLUP (source, slot)
ORDER BY source NULLS FIRST, slot NULLS FIRST;
```
Put the table in LOG.md and update STATUS.md. Then carry on with STATUS.md › Next.

## Phases
0. Measure: where the bias comes from, plus gold set and baseline (RESEARCH.md §2–3)
1. Free fixes: queries, prompt, per-material cap (§8.2)
2. First model: FashionSigLIP embeddings + linear probes (§4A2)
3. If that plateaus: LoRA VLM tagger (§4A3)
4. Production: flag, shadow mode, rollout (§9)

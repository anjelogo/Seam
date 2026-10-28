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
- **Prod DB (not verified yet, waiting on Anjelo):** it runs in Docker on Anjelo's server and listens on 127.0.0.1:5432 only (compose.yaml), so connect over Tailscale + SSH. Use a read-only role if Anjelo makes one.
  - Run one query on the server: `ssh <user>@<server> 'cd <repo> && docker compose exec -T postgres psql -U seam seam' < query.sql`
  - Or tunnel, for local tools: `ssh -N -L 5433:127.0.0.1:5432 <user>@<server>`, then `psql postgresql://seam:<password>@localhost:5433/seam`. Use 5433 because local 5432 is taken by another project.
- Old local snapshot: `data/seam.db` (SQLite, 2026-10-18, 1,107 tagged items, before Depop and the `leather` query). Queries for it are in `queries/`.
- Training box: Caden's PC (RTX 3080 Ti, 12 GB) under WSL2 (RESEARCH.md §7).
- Data and weights go in `data/models/` (gitignored).

## Step 1: is the inventory leather-heavy? (H1)
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

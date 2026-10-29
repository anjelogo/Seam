# Custom model status

Last updated: 2026-10-28 · Phase: **0 (measure)** · Branch: `caden/custom-model-training`

Goal: a Seam-owned model that (1) fixes the leather bias and (2) tags more accurately than the hosted models, starting with tagging (RESEARCH.md §8).

## In progress
- **Gold v1 labelling: 105/300 (2026-10-28).** Labelling rules so far: LOG 2026-10-28 › gold labelling session.
- **Prod scraping is stopped (found 2026-10-28).** Every row in the export is `gone` and last_seen ends 2026-10-24. Tell Anjelo; until it runs again, new exports won't have new items.

## Next (top = do first)
1. **Label gold v1 (Caden, by hand). 105/300 done (2026-10-28).** Progress lives in the browser that has label.html open, so keep using the same browser and file path. Run `python3 -I api/model/gold.py data/models/snapshots/items-2026-10-28.jsonl`, open `data/models/gold/v1/label.html`, paste the prod host, label all 300, download and save as `data/models/gold/v1/labels.jsonl`.
2. **Score the current tagger on gold v1:** `python3 -I api/model/score.py data/models/snapshots/items-2026-10-28.jsonl data/models/gold/v1`. This is the baseline every model has to beat; add it to the run table.
3. **Log the candidate pool (H3/H4).** Run 20 fixed style prompts and record the leather share in the pool and in Claude's picks. Needs active items, so local data or scraping back on.
4. **Answer the open questions below that block the first model.**

## Done
- 2026-10-28 · Material vocab v1 (api/model/material.py) and gold v1 sample + labelling page (LOG 2026-10-28)
- 2026-10-28 · H1 on prod export: leather 18.8% overall (was 11.7%), shoes 50.6%, outer 16.7% (LOG 2026-10-28)
- 2026-10-28 · Prod data access via the /admin export (`data/models/snapshots/`)
- 2026-10-20 · Research doc: options, training methods, data, path to production (RESEARCH.md)
- 2026-10-25 · H1 baseline on the 10-18 SQLite snapshot (api/model/queries/h1_sqlite.sql)
- 2026-10-25 · Model folder and documentation rules set up (AGENTS.md, STATUS.md, LOG.md, README.md)

## Decisions
- 2026-10-25 · Model work lives in `api/model/`; data and weights in `data/models/` (gitignored). Reason: Caden owns /api, and weights stay out of git.
- 2026-10-25 · Measure before training. Reason: the bias might come from the scraping or the retrieval, and no model fixes that (RESEARCH.md §2).
- 2026-10-28 · Prod data comes through the /admin export, not an SSH tunnel. Reason: Anjelo prefers not to open DB access; the export is items-only, admin-allowlisted and rate-limited.
- 2026-10-25 · The goal covers accuracy overall, not only leather. Reason: Caden wants Seam to run on its own, more accurate model.
- 2026-10-25 · Matching "leather" in listing text isn't used as a weak label. Reason: most matches were hashtags or boilerplate (LOG 2026-10-25).

- 2026-10-28 · Material vocab v1 = 24 fixed classes (incl. lace) + other/unknown, "primary material" = first part of a/b. Reason: the tagger writes ~330 free-text values; probes and gold need a fixed label set.
- 2026-10-28 · Gold labelling hides the tagger's output. Reason: showing it anchors the labeller and inflates the baseline.

## Open questions
- Prod data: how did the data get onto Anjelo's server? It isn't documented anywhere (the 10-18 HANDOFF says "nothing migrated"; the Tailscale copy was abandoned).
- Which screen showed the leather bias: tags, inventory or outfits?
- Can we train on Depop data given its ToS?
- Does Anjelo agree an eval script isn't an automated test?
- Server specs: GPU? RAM left over beyond worker-cv's 11.5 GB?

## Runs
| Run id | What | Data | Key metrics | Weights |
|---|---|---|---|---|
| _none yet_ | | | | |

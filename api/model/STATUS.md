# Custom model status

Last updated: 2026-10-28 · Phase: **0 (measure)** · Branch: `caden/custom-model-training`

Goal: a Seam-owned model that (1) fixes the leather bias and (2) tags more accurately than the hosted models, starting with tagging (RESEARCH.md §8).

## In progress
- **Prod scraping is stopped (found 2026-10-28).** Every row in the export is `gone` and last_seen ends 2026-10-24. Tell Anjelo; until it runs again, new exports won't have new items.

## Next (top = do first)
1. **Draft a material vocabulary.** A fixed list such as leather / faux_leather / suede / canvas / knit…, mapped from the ~330 free-text `tags.material` values in the 10-28 export (`h1_jsonl.py` prints them). Needed for gold labels and probes.
2. **Log the candidate pool (H3/H4).** Run 20 fixed style prompts and record the leather share in the pool and in Claude's picks. Needs active items, so local data or scraping back on.
3. **Build gold set v1.** 300 items hand-labelled for material, category, primary color and usable_for_3d (RESEARCH.md §3). Oversample shoes: 247 are tagged leather with no "leather" in the text.
4. **Score the current tagger on gold v1.** This is the baseline every model has to beat.
5. **Answer the open questions below that block step 6+.**

## Done
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

# Custom model status

Last updated: 2026-10-25 · Phase: **0 (measure)** · Branch: `caden/custom-model-research`

Goal: a Seam-owned model that fixes the leather bias, starting with tagging (RESEARCH.md §8).

## In progress
- _nothing yet_

## Next (top = do first)
1. **Find where the bias comes from (H1).** Leather share of active items, split by source and slot. Query in README.md › Step 1. Log the numbers.
2. **Log the candidate pool (H3/H4).** Run 20 fixed style prompts and record the leather share in the pool and in Claude's picks.
3. **Build gold set v1.** 300 items hand-labelled for material, category, primary color and usable_for_3d (RESEARCH.md §3).
4. **Score the current tagger on gold v1.** This is the baseline every model has to beat.
5. **Answer the open questions below that block step 6+.**

## Done
- 2026-10-20 · Research doc: options, training methods, data, path to production (RESEARCH.md)
- 2026-10-25 · Model folder and documentation rules set up (AGENTS.md, STATUS.md, LOG.md, README.md)

## Decisions
- 2026-10-25 · Model work lives in `api/model/`; data and weights in `data/models/` (gitignored). Reason: Caden owns /api, and weights stay out of git.
- 2026-10-25 · Measure before training. Reason: the bias might come from the scraping or the retrieval, and no model fixes that (RESEARCH.md §2).

## Open questions
- Which screen showed the leather bias: tags, inventory or outfits?
- Can we train on Depop data given its ToS?
- Does Anjelo agree an eval script isn't an automated test?
- Server specs: GPU? RAM left over beyond worker-cv's 11.5 GB?

## Runs
| Run id | What | Data | Key metrics | Weights |
|---|---|---|---|---|
| _none yet_ | | | | |

# /api/model — custom model (Caden)

Everything to do with developing, training and evaluating Seam's own model lives here.
The docs in this folder are the project's memory. If something isn't written here, it didn't happen.

## Before any model work
1. Read the root AGENTS.md and api/AGENTS.md (the repo rules still apply).
2. Read STATUS.md. It says what's in progress, what's next and what's done.
3. Read the top 5 entries of LOG.md, or more if STATUS.md points you to an older one.
4. Read RESEARCH.md only for background or when a decision needs it.
5. Tell your human which STATUS.md item you're about to pick up before you start.

## Documentation rules (mandatory)
- **Every working session leaves a LOG.md entry**, even if nothing worked. Add it to the top, newest first, in the format below.
- **STATUS.md is always current.** Update it in the same commit as the work: move items between In progress / Next / Done, and add new decisions and open questions.
- **Log the failures too.** Dead ends, bad runs and abandoned ideas go in LOG.md with the reason, so nobody repeats them.
- **Numbers, not adjectives.** Write "leather precision 0.71 → 0.88 on gold v1", not "much better". Always name the eval set and version.
- **Every training or eval run gets a run id** (`YYYYMMDD-short-name`) and an entry in the STATUS.md run table: data snapshot, config, key metrics, where the weights are.
- **Decisions get a line in STATUS.md › Decisions** with the date and the reason. Reversing one needs a new line, not an edit.
- **Before ending a session**, make sure STATUS.md › Next is accurate, so the next agent knows exactly what to do first.
- Keep entries short. Link to files, commits and run ids rather than pasting output.

## LOG.md entry format
```
## YYYY-MM-DD · who (caden|agent) · short title
- did: what was done
- result: numbers / outcome / what failed and why
- files: paths, commits, run ids
- next: the follow-up this creates (also added to STATUS.md)
```

## Where things go
- Code: `api/model/` (a separate uv package once there's code, the way gen3d/drape is).
- Datasets, snapshots, weights: `data/models/<run-id>/` (gitignored). Never commit weights or scraped images.
- Labels we make by hand (gold set): `data/models/gold/<version>/`. Note its size and how it was sampled in LOG.md.

## Boundaries
- Nothing here goes into the live pipeline (`app/cv/tag.py`, `app/llm/`) without asking Caden first. Wire it in behind a flag (RESEARCH.md §9).
- Schema changes (new tag fields, enum changes) follow the root contract rules and need a HANDOFF.md entry. `Category` changes need Anjelo.
- Eval scripts print reports. They are not automated tests (see RESEARCH.md §3 about confirming this with Anjelo).

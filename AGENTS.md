# Seam — agent rules

Two humans, separate agents. Anjelo: /gen3d, /web, /assets. Caden: /api. Shared: /shared/schema.

## Before any work
1. Read .agents/HANDOFF.md fully. Newest entries at top.
2. Read the AGENTS.md in the folder you are working in.
3. Read shared/schema/models.py. It is the contract.

## Contract rules
- models.py is source of truth; types.ts mirrors it by hand. Change both in the same commit.
- Additive optional fields: allowed, must be logged in HANDOFF.md.
- Renames, removals, type changes, new required fields: STOP and ask your human. Never do it alone.
- Never edit files outside your owner's folders except shared/schema (contract changes) and .agents/HANDOFF.md.
- Money = integer cents. Item.id = "source:source_id". Every endpoint body is a model from models.py.

## After any change the other side depends on
Endpoint added/changed, schema field added, port/env var changed, new run step:
append an entry to the TOP of .agents/HANDOFF.md in the same commit.

## Hard constraints
- Comments only when strictly necessary, one short line. TODO(caden)/TODO(anjelo) for hand-off points.
- No automated tests (no Playwright, Vitest, Jest, pytest). Testing is manual.
- Commits: `type(scope): short lowercase desc`, ≤50 chars, subject only. Types: feat fix chore refactor docs style perf build.
- Never add Co-Authored-By or any attribution to commits.
- No live third-party calls during the demo path; cache to data/.
- No frontend UI until a design spec exists.

## Ports
api 8000 · gen3d 8001 · web 5173. `make dev` runs all three.

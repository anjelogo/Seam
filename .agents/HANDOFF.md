# Handoff log

Newest first. One entry per change the other side depends on. Keep entries ≤5 lines.

Format:
## YYYY-MM-DD HH:MM · who (anjelo|caden) · area
- what changed
- action needed: <none | what the other side must do>

---

## 2026-10-17 · caden · api tagging
- new run step: `cd api && uv run python -m app.cv [limit]` tags untagged items (Mk1.5 x2 -> Gemini fallback), writes items.tags
- clean_image = 1024² RGBA PNG at data/clean/<source>_<source_id>.png, url /static/clean/...; also written for usable_for_3d=false items
- hangers/mannequins/bodies are segmented out; new unusable_reason values: "extra_objects: <names>" (bag, belt, jewelry... left or covering), "cutout_incomplete"
- new env vars PERCEPTRON_API_KEY, FAL_KEY (optional: Isaac condition check runs on fal; without it Mk1.5 does the check)
- action needed: none; queue GenJobs only where tags.usable_for_3d

## 2026-10-17 · caden · api ingest
- POST /ingest/run {"queries":[str],"sources":[Source]} -> {"added":int}; dev-only seeding, adapters: poshmark, grailed, ebay (needs EBAY_APP_ID/EBAY_CERT_ID)
- sqlite store at $DATA_DIR/seam.db, table items(id, source, listing json, tags json); images cached to data/raw/<source>/, ImageRef.url = /static/raw/...
- depop + mercari return 403 (cloudflare), dropped
- action needed: none; /items + /outfits still serve the fixture until tagging lands

## 2026-10-17 · anjelo · repo
- scaffolded monorepo; /api and /gen3d serve fixture mocks; /web is an empty shell with typed api client
- schema v2 merged (StyleQuery.body, previous_outfit_ids, feedback; ItemTags.est_retail, tagger, garment_box)
- action needed (caden): replace mock handlers in api/app/routes/ keeping same models; confirm shipping in totals, unique outfit ids per request, refine state storage

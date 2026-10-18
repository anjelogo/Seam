# Handoff log

Newest first. One entry per change the other side depends on. Keep entries ≤5 lines.

Format:
## YYYY-MM-DD HH:MM · who (anjelo|caden) · area
- what changed
- action needed: <none | what the other side must do>

---

## 2026-10-17 18:20 · anjelo · gen3d
- avatar = procedural mannequin: assets/avatar_{masc,fem}.glb (Y-up, faces +Z, feet at origin), morph targets = BODY_SLIDERS, influence = slider value; anchors in assets/anchors.json
- templates: assets/templates/<id>_<base>.glb, same morph targets; template_textured asset glb_url = masc, fem is the same path with `_fem.glb`
- backends mock/fal/local via GEN3D_BACKEND (default mock); env FAL_KEY, GEN3D_BACKEND, ASSETS_DIR; gen3d/app/settings.py loads root .env; fal = fal-ai/trellis-2 (~55 s/job), texturing via fal-ai/trellis-2/retexture baked onto template UVs (not run live yet, mock fallback)
- assets table in DATA_DIR/seam.db (item_id, json = Asset3D, updated_at), upserted on every status change
- action needed (caden): join assets onto Item.asset; api /static serves all of DATA_DIR incl. seam.db, mount only subfolders like gen3d does

## 2026-10-17 · caden · api ingest
- POST /ingest/run {"queries":[str],"sources":[Source]} -> {"added":int}; dev-only seeding, adapters: poshmark, grailed, ebay (needs EBAY_APP_ID/EBAY_CERT_ID)
- sqlite store at $DATA_DIR/seam.db, table items(id, source, listing json, tags json); images cached to data/raw/<source>/, ImageRef.url = /static/raw/...
- depop + mercari return 403 (cloudflare), dropped
- action needed: none; /items + /outfits still serve the fixture until tagging lands

## 2026-10-17 · anjelo · repo
- scaffolded monorepo; /api and /gen3d serve fixture mocks; /web is an empty shell with typed api client
- schema v2 merged (StyleQuery.body, previous_outfit_ids, feedback; ItemTags.est_retail, tagger, garment_box)
- action needed (caden): replace mock handlers in api/app/routes/ keeping same models; confirm shipping in totals, unique outfit ids per request, refine state storage

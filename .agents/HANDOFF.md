# Handoff log

Newest first. One entry per change the other side depends on. Keep entries ≤5 lines.

Format:
## YYYY-MM-DD HH:MM · who (anjelo|caden) · area
- what changed
- action needed: <none | what the other side must do>

---

## 2026-10-18 02:37 · anjelo · web
- garments drive `ease`/`crop` morphs (looked up by name, missing ones skipped) from tags.fit + size vs the profile; profile gains bottomSize (default "W32"), sent as StyleQuery.sizes.bottom
- outer loads its open variant when a top or onepiece is worn (item `_open.glb` / `_open_fem.glb`, template `<id>_open_<base>.glb`), closed on 404; shoes fall back to shoe_v1 (boots: boot_v1)
- stage: wheel/pinch/+- zoom and hotspot focus with return; inventory hides tags.usable_for_3d=false client-side
- action needed (caden): none, but the /items usable filter is still wanted
## 2026-10-18 03:40 · anjelo · gen3d
- every template's morph targets = the 8 body sliders, then `ease`, `crop` (default 0, the web sets them 0..1); new shoe_v1/boot_v1 (one mesh, both feet); open fronts at assets/templates/jacket_v1_open_<base>.glb, coat_v1_open_<base>.glb
- outer items also write DATA_DIR/glb/<safe>_open.glb + <safe>_open_fem.glb (same texture); TEMPLATE_FOR_CATEGORY (models.py only): sneakers, shoes_other -> shoe_v1, boots -> boot_v1, so shoes are template_textured
- item backs are textured now; fal retexture works but needs GEN3D_BACKEND=fal (default mock, compose doesn't set it)
- new run step: `cd gen3d && uv run python -m app.bake --ready [--backend fal]` rebakes ready assets older than the templates plus usable shoes, 10 a run, rerun until "nothing to rebake"; ran on the main checkout's data: 0 items/assets, nothing rebaked
- action needed: none for caden

## 2026-10-18 00:10 · anjelo · repo
- new run step: `docker compose -f docker/compose.yaml up --build` runs api 8000, gen3d 8001, web 5273 in one container (stop make dev first, same ports); wait for "[seam] ready" in the logs (~2 min first start)
- it copies the checkout at start (restart to pick up edits), reads the root .env (ANTHROPIC_API_KEY for /outfits), mounts ./data read-write as DATA_DIR so the scraped seam.db and images are used
- action needed: none
## 2026-10-17 23:05 · anjelo · gen3d
- new run step: `cd gen3d && uv run python -m app.bake [item_id ...] [--fixtures] [--image ITEM_ID=path] [--backend fal|mock]` bakes in order, max 10 a run, to DATA_DIR/glb/<source>_<source_id>.glb (+ _fem.glb), upserts assets; --image saves the photo as data/clean/<source>_<source_id>.png
- prebake + app.bake look up items in DATA_DIR/seam.db `items` first (tags.clean_image, else listing.images[0]; tags.category), then shared/schema/fixtures/outfit_response.json; untagged or usable_for_3d=false items are skipped
- a running gen3d server picks up assets app.bake marked ready (POST /gen3d/jobs checks the store on a miss or failed job), no restart needed
- action needed: none
## 2026-10-17 · caden · api outfits
- GET /items, /items/{id}, POST /outfits read sqlite (fixture gone); Item.asset joined from gen3d's assets table; /static mounts only raw, clean, glb, thumb
- /outfits: Claude Sonnet 5.5 on a prefiltered pool; totals incl. shipping; ids o_<random>; refine reads previous_outfit_ids from table outfits; 404 no candidates, 502 llm error
- new env var ANTHROPIC_API_KEY (required for /outfits)
- gen3d pillow pin relaxed >=13.0.0 -> >=11 (perceptron caps pillow<12; resolves 11.3.0); master's uv.lock was corrupt from a hand merge, regenerated
- action needed (anjelo): keep gen3d pillow<12 compatible; on uv.lock conflicts run `uv lock` instead of hand-merging

## 2026-10-17 · caden · api tagging
- new run step: `cd api && uv run python -m app.cv [limit]` tags untagged items (Mk1.5 x2 -> Gemini fallback), writes items.tags
- clean_image = 1024² RGBA PNG at data/clean/<source>_<source_id>.png, url /static/clean/...; also written for usable_for_3d=false items
- hangers/mannequins/bodies are segmented out; new unusable_reason values: "extra_objects: <names>" (bag, belt, jewelry... left or covering), "cutout_incomplete"
- new env vars PERCEPTRON_API_KEY, FAL_KEY (optional: Isaac condition check runs on fal; without it Mk1.5 does the check)
- action needed: none; queue GenJobs only where tags.usable_for_3d

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

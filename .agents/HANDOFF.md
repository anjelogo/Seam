# Handoff log

Newest first. One entry per change the other side depends on. Keep entries ≤5 lines.

Format:
## YYYY-MM-DD HH:MM · who (anjelo|caden) · area
- what changed
- action needed: <none | what the other side must do>

---

## 2026-10-21 00:25 · anjelo · gen3d drape texture v2
- gen3d/drape now textures in sewing-pattern space (branch anjelo/texture-v2): listing photos -> PatternSpec via Claude (drape/spec.py) -> delit albedo -> per-panel cm rasters (stripes on grain, side stripes on the outseam, registered prints) -> UV atlas -> GLB; the old front projection stays behind `--legacy`
- PatternSpec/StripeSet/Trim/Placement are a local copy in gen3d/drape/drape/patternspec.py; switch the import to shared/schema once garments-v3 merges
- bottoms hold the waist for the whole sim, tops drape in a 45° A-pose and bind back to the 20° web pose (tees still ride ~6 cm low: mannequin shoulders); eval set via `python -m drape.inputs --set texture`, scores + screenshots in gen3d/drape/RESULTS_TEXTURE.md
- action needed: none (gen3d drape only, nothing wired into prod)

## 2026-10-20 21:05 · anjelo · gen3d drape poc
- sewing-pattern + cloth-sim PoC lives in gen3d/drape (own uv package; nothing wired into prod): 4 real prod items -> Claude design params -> pygarment patterns on size bodies -> our mannequin exported as a GarmentCode body; panel texturing, morph-bound GLBs (web useBodyMorphs-compatible) and a side-by-side viewer all run locally
- the warp cloth sim itself needs a CUDA box: drape/scripts/setup_gpu.sh + run_poc.sh are ready, local CPU sim segfaults (documented); numbers, screenshots, license flag (warp fork is non-commercial) and verdict in gen3d/drape/RESULTS.md
- action needed: none (PoC only)

## 2026-10-19 13:50 · anjelo · api depop volume
- depop searches run twice (gender=female, gender=male; unfiltered returns the same 24 as female) and the worker keeps all 48 per (query, slot), vs 12 for the other sources
- SCRAPE_QUERIES default adds denim, leather, 90s, carhartt (10 queries): ~2,900 raw listings a night across sources, more than the ~1,400/day one cv job can tag, so the untagged backlog grows
- tag jobs now skip items that are no longer active (expired or sold before their turn) instead of paying Perceptron for them
- action needed: none
## 2026-10-19 13:10 · anjelo · api depop + cv memory
- new adapter Source.depop (app/sources/depop.py): parses the www.depop.com/search/ page (Next.js flight data), first 24 results per query only (page>0 returns []), q = query + SLOT_WORD; title = first line of the description (depop has no title); seller not in the search data; robots.txt disallows /search/* and Depop's ToS bans scraping, risk accepted by anjelo
- web STORE_SOURCES gains depop (building screen chips), in BUILDING_SPEC order
- one tag job peaks ~11.5 GB RAM (birefnet ~7.8 GB + SAM), ~53 s per item on the CT's 4 cores; CV_CONCURRENCY default is now 1 (was 4, which OOM-killed worker-cv in a loop); each tag job runs in its own spawned process so the memory comes back after every item; tagging can't run on an 8 GB laptop
- action needed (caden): if you touch cutout.py, onnxruntime memory (cpu mem arena, input size) is the lever for running more than one cv job
## 2026-10-19 12:20 · anjelo · repo gluetun + scraping speed
- new opt-in compose profile `vpn`: Seam's own gluetun (qmcgaw/gluetun:v3, HTTP proxy :8888, control :8000, compose network only); provider settings go in a gitignored gluetun.env next to .env; the CT needs /dev/net/tun (`pct set <ctid> -dev0 /dev/net/tun`)
- to use it: `docker compose --profile prod --profile vpn up -d` with SCRAPE_PROXY=http://gluetun:8888 and GLUETUN_CONTROL_URL=http://gluetun:8000 in .env; GLUETUN_ROTATE=true is safe there (nothing else rides that VPN)
- scrape_all queues sources interleaved so all sources scrape at once, and photo downloads skip the SCRAPE_MIN_INTERVAL_MS spacing (own 3-in-flight cap per source): one query cycle went 293 s -> 131 s
- action needed: none
## 2026-10-18 23:25 · anjelo · repo tunnel
- new optional env var TUNNEL_TOKEN: set = cloudflared runs your Cloudflare dashboard tunnel (point its public hostname at http://web:80), empty = quick tunnel on a random trycloudflare.com URL as before
- with a hostname, add its https origin to PUBLIC_ORIGINS (comma list) or logins through it get 403; apply with `docker compose --profile prod up -d tunnel api`
- action needed: none
## 2026-10-18 22:45 · anjelo · repo run steps
- Postgres replaces SQLite (data/seam.db is gone, nothing migrated): `make db` starts postgres on 127.0.0.1:5432 and applies shared/migrations, `make psql` opens a shell, then `make dev` on the host as before
- one root compose.yaml: `docker compose --profile dev up --build` (one-container dev stack + postgres) or `docker compose --profile prod up --build -d` (api, gen3d, worker, worker-cv, caddy on :8080, tunnel); in a Proxmox LXC run `bash docker/ct-setup.sh`
- Python 3.12 everywhere (.python-version, Dockerfiles); run `uv sync --all-packages` once to rebuild .venv
- action needed (both): add POSTGRES_PASSWORD=seam to your .env (compose refuses to parse without it) plus the vars below
## 2026-10-18 22:45 · anjelo · env vars
- new: DATABASE_URL (host default postgresql://seam:seam@localhost:5432/seam, compose points it at postgres), POSTGRES_PASSWORD, PUBLIC_ORIGINS (comma list for the Origin check), COOKIE_SECURE (true in prod), SESSION_TTL_DAYS=30
- scraping, all optional (empty = direct, no challenge solving, no rotation): SCRAPE_PROXY (gluetun http proxy), FLARESOLVERR_URL, GLUETUN_CONTROL_URL, GLUETUN_CONTROL_AUTH, GLUETUN_ROTATE=false
- tuning: SCRAPE_CONCURRENCY_PER_SOURCE=3, SCRAPE_MIN_INTERVAL_MS=500, SCRAPE_QUERIES, SCRAPE_PAGES=1, SCRAPE_CRON="0 9 * * *" (UTC), STALE_HOURS=72, CV_CONCURRENCY=4
- action needed: copy them from .env.example
## 2026-10-18 22:45 · anjelo · api auth
- cookie sessions (`seam_session`): POST /auth/signup {name,email,password} 201|409|422, POST /auth/login 200|401|429, POST /auth/logout 204, GET /auth/me 200|401, GET /auth/check 204 + X-User-Id (Caddy forward_auth on /gen3d/*)
- GET/PUT /me/profile {body} (the whole web profile), GET/POST /me/looks, DELETE /me/looks/{id}; POST /outfits requires login and reads refine history per user
- auth errors add an optional `field` to the ApiError body (local to the auth routes, schema unchanged); writes with a foreign Origin get 403; login and signup allow 10 tries per 15 min per IP and per email
- action needed (caden): routes that need a user take `Depends(current_user)` from app.auth.deps
## 2026-10-18 22:45 · anjelo · api worker
- POST /ingest/run and app/ingest.py are gone; from api/: `uv run python -m app.worker --queues scrape,default,cv [--once]`, `... enqueue-all` (one scrape_all by hand), `... status` (last 20 scrape_runs)
- scrape_all runs on SCRAPE_CRON over sources x SCRAPE_QUERIES x top/bottom/outer/shoes x pages; each job keeps 4 photos per listing in data/raw and defers tag(item_id) on the cv queue; expire_stale runs hourly
- adapters are async via app/sources/fetch.py (curl_cffi, per-source limits, retries, FlareSolverr on Cloudflare challenges); Perceptron and eBay use the direct api_client / api_aclient
- run one scrape worker process only (rate limits live in memory); worker-cv can scale
- action needed (caden): tagging needs PERCEPTRON_API_KEY; with only FAL_KEY set the perceptron SDK picks provider fal and every tag job fails
## 2026-10-18 22:45 · anjelo · what moved
- all DB access is shared/seam_shared/db.py (`from seam_shared import db`); schema in shared/migrations/001_init.sql, applied by `python -m seam_shared.migrate`; api/app/db.py is gone and DATA_DIR lives in api/app/settings.py
- docker/prod/* moved up to docker/ (backend.Dockerfile, web.Dockerfile, Caddyfile, ct-setup.sh); docker/Dockerfile is docker/dev.Dockerfile; docker/compose.yaml and docker/prod/compose.yaml became the root compose.yaml
- `cd api && uv run python -m app.cv [limit]` still tags untagged items by hand
- action needed: none

## 2026-10-18 · caden · api qa fixes
- issue 2: GET /items and the /outfits pool now return only tags.usable_for_3d = true items; `?include_unusable=true` on either shows everything (debug)
- issue 6: tags.size_normalized is on one ladder per slot: top/outer/onepiece XS S M L XL XXL, bottom W26..W40 (integer waist), shoes US<n> (e.g. US9.5), accessory null
- existing rows are re-mapped by `cd api && uv run python -m app.cv` (runs the backfill first; no API calls if nothing is untagged); StyleQuery.sizes are mapped onto the same ladder before matching
- action needed (anjelo): issue 6 size delta can compare size_normalized against the user's pills directly; untagged or unusable items no longer come back from /items
## 2026-10-18 03:40 · anjelo · gen3d
- every template's morph targets = the 8 body sliders, then `ease`, `crop` (default 0, the web sets them 0..1); new shoe_v1/boot_v1 (one mesh, both feet); open fronts at assets/templates/jacket_v1_open_<base>.glb, coat_v1_open_<base>.glb
- outer items also write DATA_DIR/glb/<safe>_open.glb + <safe>_open_fem.glb (same texture); TEMPLATE_FOR_CATEGORY (models.py only): sneakers, shoes_other -> shoe_v1, boots -> boot_v1, so shoes are template_textured
- item backs are textured now; fal retexture works but needs GEN3D_BACKEND=fal (default mock, compose doesn't set it)
- new run step: `cd gen3d && uv run python -m app.bake --ready [--backend fal]` rebakes ready assets older than the templates plus usable shoes, 10 a run, rerun until "nothing to rebake"; ran on the main checkout's data: 0 items/assets, nothing rebaked
- action needed: none for caden
## 2026-10-18 02:37 · anjelo · web
- garments drive `ease`/`crop` morphs (looked up by name, missing ones skipped) from tags.fit + size vs the profile; profile gains bottomSize (default "W32"), sent as StyleQuery.sizes.bottom
- outer loads its open variant when a top or onepiece is worn (item `_open.glb` / `_open_fem.glb`, template `<id>_open_<base>.glb`), closed on 404; shoes fall back to shoe_v1 (boots: boot_v1)
- stage: wheel/pinch/+- zoom and hotspot focus with return; inventory hides tags.usable_for_3d=false client-side
- action needed (caden): none, but the /items usable filter is still wanted

## 2026-10-17 23:05 · anjelo · gen3d
- new run step: `cd gen3d && uv run python -m app.bake [item_id ...] [--fixtures] [--image ITEM_ID=path] [--backend fal|mock]` bakes in order, max 10 a run, to DATA_DIR/glb/<source>_<source_id>.glb (+ _fem.glb), upserts assets; --image saves the photo as data/clean/<source>_<source_id>.png
- prebake + app.bake look up items in the `items` table first (tags.clean_image, else listing.images[0]; tags.category), then shared/schema/fixtures/outfit_response.json; untagged or usable_for_3d=false items are skipped
- a running gen3d server picks up assets app.bake marked ready (POST /gen3d/jobs checks the store on a miss or failed job), no restart needed
- action needed: none
## 2026-10-17 · caden · api outfits
- GET /items, /items/{id}, POST /outfits read the db (fixture gone); Item.asset joined from gen3d's assets table; /static mounts only raw, clean, glb, thumb
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
- assets table (item_id, json = Asset3D, updated_at), upserted on every status change
- action needed: none

## 2026-10-17 · anjelo · repo
- scaffolded monorepo; /api and /gen3d serve fixture mocks; /web is an empty shell with typed api client
- schema v2 merged (StyleQuery.body, previous_outfit_ids, feedback; ItemTags.est_retail, tagger, garment_box)
- action needed (caden): replace mock handlers in api/app/routes/ keeping same models; confirm shipping in totals, unique outfit ids per request, refine state storage

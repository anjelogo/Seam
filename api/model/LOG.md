# Custom model log

Newest first. One entry per working session. Format and rules in AGENTS.md.

---

## 2026-10-28 · caden · gold labelling session
- did: labelled 105/300 gold v1 items in `data/models/gold/v1/label.html`; added colors silver, gold and material lace mid-session (sample unchanged, md5 fc62a919)
- result: labelling rules agreed. Material = what the main body visibly is (lace only if most of the item; trim doesn't count). Shoes usable = whole shoe/pair, alone, any angle (a pair is one item); no if only sole/tag/detail/cropped/several pairs. Halter and tube tops → `tank`; cropped tops go by sleeve (tee/longsleeve/tank), cropped is a fit, not a category
- open: which shoe angles gen3d's shoe template bakes well (ask Anjelo); halter/tube tops have no strapless template
- next: finish labelling (195 left), download labels.jsonl, run score.py

## 2026-10-28 · agent · material vocab v1 + gold v1 sample
- did: material vocab v1 (`api/model/material.py`): 24 classes + other/unknown (lace added mid-labelling), regex rules, first match wins, primary material = first part of "a/b". Sampled gold v1 (`api/model/gold.py`, seed 20261028) and built a local labelling page; wrote `api/model/score.py` for the baseline
- result: vocab maps the 10-28 export's ~330 strings with 9 of 8,656 tagged items left as `other` (wood, metal, quilted fabric…); 1,354 `unknown` (1,283 have no material). Gold v1 = 300 items: 60 shoes tagged leather with no text match, 40 non-shoe leather-tagged, 200 by slot (top/bottom/outer 50, shoes 40, onepiece/accessory 5). The page hides the tagger's labels so they don't anchor the labeller. Colors: 14 basic + silver and gold (added mid-labelling, no labels changed). score.py checked on 20 fake labels only
- files: api/model/material.py, gold.py, gold_label.html, score.py; data/models/gold/v1/{sample.jsonl,label.html} (gitignored)
- next: Caden labels gold v1, then run score.py for the baseline

## 2026-10-28 · agent · H1 on the prod export
- did: Caden exported prod via /admin to `data/models/snapshots/items-2026-10-28.jsonl` (9,122 rows: depop 6,222, poshmark 1,738, grailed 1,162; 8,656 tagged). Ran H1 on all tagged rows with `api/model/queries/h1_jsonl.py`
- result (prod health): **all 9,122 rows are `status = gone`**. last_seen stops at 2026-10-24, so scraping stopped then and expire_stale (72 h) expired everything. H1 counts every status for that reason
- result (H1): leather 11.7% → **18.8%** overall vs the 10-18 snapshot. Shoes 39.2% → 50.6%, outer 3.0% → 16.7%, bottom 0.5% → 8.5%, top 0.0% → 5.0%. Depop 18.9%, grailed 17.7%, poshmark 19.2% (poshmark-only was 11.7%). So after the `leather` query the inventory is leather-heavy, mostly in shoes and outerwear
- result (H2 hint): 247 of 1,755 shoes are tagged leather with no "leather" in the listing text (was 21 on the snapshot), which supports "the tagger defaults shoes to leather". Unverified until gold v1
- result (vocab): `tags.material` has ~330 distinct strings; 1,283 tagged items have none, and 51 say "unknown"
- files: api/model/queries/h1_jsonl.py, data/models/snapshots/items-2026-10-28.jsonl (gitignored)
- next: tell Anjelo scraping is stopped; draft the material vocabulary from this export; H3/H4 candidate pool

## 2026-10-28 · agent · admin export for prod data
- did: built /admin (web) + GET /admin/stats and GET /admin/export/items (api). Admins = ADMIN_EMAILS allowlist; others get 404. The export streams a fixed column list from `items` only, rate-limited (10 / 15 min) and logged. Design mockup: https://claude.ai/artifact/7GqXG6XbujnFV8Qtjgggf7
- result: anonymous requests 401 (checked locally); the admin path and the export itself are untested, no local Postgres
- files: api/app/routes/admin.py, api/app/auth/deps.py, web/src/routes/Admin.tsx, .agents/HANDOFF.md
- next: Anjelo deploys and sets ADMIN_EMAILS; export, snapshot to data/models/snapshots/, rerun H1 on it

## 2026-10-25 · agent · prod DB access
- did: worked out how to reach the prod DB. It's on Anjelo's server in Docker, bound to 127.0.0.1:5432 (compose.yaml:36). The Cloudflare tunnel only exposes web:80. There's no documentation of how the data got there (HANDOFF 10-18 says "nothing migrated"; Caden's Tailscale migration was abandoned as too slow)
- result: access has to go through Tailscale + SSH. Tailscale is installed on Caden's Mac but stopped. Asked Anjelo for the server name, SSH user, repo path, DB password or read-only role, and to add Caden's SSH key. **Blocked until he replies**
- files: api/model/README.md › Setup (connection plan, unverified), STATUS.md
- next: draft the material vocabulary while waiting; once access exists, rerun H1 on prod and mark the README steps as verified

## 2026-10-25 · agent · H1 on the 10-18 snapshot
- did: no Seam Postgres locally (the 5432 server is another project's), so I ran H1 on `data/seam.db`, the SQLite snapshot from 2026-10-18: 1,107 tagged items (poshmark 1,059, grailed 48, no depop). This snapshot predates the `leather` scrape query (added in cfa9000, 2026-10-19 20:17), so it's a "before" baseline, not prod
- result: items tagged leather = 11.7% overall. By slot (poshmark): shoes 39.2%, outer 3.0%, bottom 0.5%, top 0.0%. Grailed: shoes 91.7%, outer 38.5% (n=12 and 13, too small to trust). Without the leather query, the inventory is not leather-heavy outside shoes
- result (H2 hint): 21 poshmark shoes are tagged `leather` with no "leather" anywhere in the listing text (flip-flops, beach sandals, Skechers knit, Vans canvas). The tagger seems to fall back to leather for shoes it isn't sure about. Unverified, needs the gold set
- result (accuracy): `material` is free text, with 12 spellings of leather (leather, faux leather, faux_leather, synthetic_leather, patent leather, mesh/leather…). Any probe needs a fixed material vocabulary first. 59 shoes have no material at all
- failed: a "leather" text search is no good as a weak label. Most text-only hits are hashtags or boilerplate (sheer dresses, cotton pants), and the tags on those were right
- files: api/model/queries/h1_sqlite.sql
- next: rerun H1 on prod (after the leather query) to measure its effect; draft a material vocabulary

## 2026-10-25 · caden · documentation set up
- did: made `api/model/` with AGENTS.md (rules), STATUS.md (board), LOG.md, README.md (getting started); moved `api/docs/custom-model-research.md` to RESEARCH.md
- result: no model work yet; phase 0 (measure) is next
- files: api/model/*
- next: STATUS.md › Next #1 (leather share SQL)

## 2026-10-20 · caden · research
- did: looked at where models run today, four hypotheses for the leather bias, model options A–D, training methods, datasets, hardware, path to production
- result: plan is measure → free fixes → FashionSigLIP + linear probes → LoRA VLM if needed
- files: api/model/RESEARCH.md
- next: measure (RESEARCH.md §8 step 1)

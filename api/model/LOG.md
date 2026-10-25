# Custom model log

Newest first. One entry per working session. Format and rules in AGENTS.md.

---

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

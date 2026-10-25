# /api — Caden

Owns: ingest (app/sources), cutout + tagging (app/cv), outfit LLM (app/llm), SQLite (app/db.py), routes.
Serves: POST /outfits, GET /items, GET /items/{id}, GET /health, /static.
Consumes from gen3d: Asset3D rows joined onto Item.asset.
Must produce for gen3d: ItemTags.clean_image (RGBA PNG, 1024², garment centered), category (exact enum), usable_for_3d honest.
Do not touch /gen3d or /web.
Custom model work: read api/model/AGENTS.md first and follow its documentation rules.

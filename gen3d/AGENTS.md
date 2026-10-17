# /gen3d — Anjelo

Owns: TRELLIS.2 wrapper (app/pipeline), job queue (app/jobs.py), fitting, GLB + thumbnail output.
Serves: POST /gen3d/jobs, GET /gen3d/jobs/{item_id}, POST /gen3d/prebake, GET /health, /static.
Decides AssetTier; ignore any tier sent by /api.
GPU host order: Vultr → RunPod → fal.ai, always behind this same API.
Do not touch /api.

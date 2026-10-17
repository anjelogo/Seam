# Seam

Thrift outfits from a vibe, tried on in 3D before you buy. DubHacks 2026.

## Run

Needs Python 3.11+, uv, Node 22.12+.

```sh
cp .env.example .env
make install
make dev
```

`make dev` starts all three services with prefixed logs. `make api`, `make gen3d` or `make web` starts one.

## Ports and owners

| Folder | What | Port | Owner |
| --- | --- | --- | --- |
| `api/` | FastAPI: ingest, CV tagging, outfit LLM | 8000 | Caden |
| `gen3d/` | FastAPI: 2D to 3D (TRELLIS.2) | 8001 | Anjelo |
| `web/` | Vite + React + TS | 5173 | Anjelo |
| `assets/` | avatar and template GLBs | | Anjelo |
| `shared/schema/` | API contract, `models.py` is the source of truth | | both |

The web dev server proxies `/api` to :8000 (prefix stripped), `/gen3d` to :8001 and `/static` to :8000.
Both backends serve mock data from `shared/schema/fixtures/` until the real logic lands.

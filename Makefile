.PHONY: install dev api gen3d web db psql

install:
	uv sync --all-packages
	cd web && npm install

dev:
	web/node_modules/.bin/concurrently -n api,gen3d,web -c blue,magenta,green "$(MAKE) -s api" "$(MAKE) -s gen3d" "$(MAKE) -s web"

api:
	cd api && uv run uvicorn app.main:app --reload --port 8000

gen3d:
	cd gen3d && uv run uvicorn app.main:app --reload --port 8001

web:
	cd web && npm run dev

db:
	docker compose --profile dev up -d postgres && docker compose --profile dev run --rm migrate

psql:
	docker compose exec postgres psql -U seam seam

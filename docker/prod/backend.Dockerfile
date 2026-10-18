# one image for both python services (api + gen3d), built from the repo root
# no BuildKit cache mounts, so it also builds on plain docker.io / legacy builders inside an LXC
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /app

# deps first so code edits don't reinstall everything
COPY pyproject.toml uv.lock ./
COPY shared/pyproject.toml shared/
COPY api/pyproject.toml api/
COPY gen3d/pyproject.toml gen3d/
RUN uv sync --frozen --all-packages --no-install-workspace --no-cache

COPY shared shared
COPY api api
COPY gen3d gen3d
COPY assets assets
RUN uv sync --frozen --all-packages --no-cache

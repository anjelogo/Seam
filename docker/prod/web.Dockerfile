# build the vite app, serve it with caddy, which also proxies the backends
FROM node:22-bookworm-slim AS build
WORKDIR /app
COPY web/package.json web/package-lock.json web/
RUN cd web && npm ci --no-audit --no-fund --loglevel=error
COPY shared/schema shared/schema
COPY web web
RUN cd web && npm run build

FROM caddy:2-alpine
COPY docker/prod/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/web/dist /srv

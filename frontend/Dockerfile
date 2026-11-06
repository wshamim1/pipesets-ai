# ── Build stage ───────────────────────────────────────────────────────────────
FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# The user guide shown in Docs lives in the repo's docs/guide/, outside this build context. It comes in
# as the extra build context "docs" (compose: additional_contexts; docker/podman build:
# --build-context docs=docs/guide) and lands where src/utils/guides.ts imports it from.
COPY --from=docs . /docs/guide/
# The UI calls the API through the nginx reverse proxy at /api (same origin).
ARG VITE_API_BASE=/api
ENV VITE_API_BASE=${VITE_API_BASE}
# Shown to users as the address for /v1 and webhooks, e.g. https://api.example.com (deploy/edge)
ARG VITE_PUBLIC_API_URL=
ENV VITE_PUBLIC_API_URL=${VITE_PUBLIC_API_URL}
# Where the builder UI lives, for the chat page's "Open in Pipesets" link, e.g. https://app.example.com
# (deploy/edge). Empty = the page's own origin.
ARG VITE_UI_URL=
ENV VITE_UI_URL=${VITE_UI_URL}
RUN npm run build

# ── Runtime stage (non-root, listens on 8080) ─────────────────────────────────
FROM nginxinc/nginx-unprivileged:1.27-alpine

# *.template files are rendered with envsubst at start-up (BACKEND_URL).
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

ENV BACKEND_URL=http://backend:8000

EXPOSE 8080

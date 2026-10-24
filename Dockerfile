# One image: the built frontend, served by the FastAPI backend on port 8000.
#   docker build -t github-galaxy .
#   docker run -p 8000:8000 -e GITHUB_TOKEN=... -v galaxy-cache:/data github-galaxy

FROM node:24-alpine AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev
COPY --from=web /app/frontend/dist /app/frontend/dist

ENV CACHE_DIR=/data GALAXY_NO_GH_CLI=1
VOLUME /data
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "galaxy", "serve", "--host", "0.0.0.0", "--port", "8000"]

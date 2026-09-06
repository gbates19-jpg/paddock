# UNTESTED — written on a Mac with no local Docker install (see docs/phase1.md
# neighbour ../README.md "Docker" section). Review on first real build/run.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /uvx /bin/

WORKDIR /app

# Dependencies first so `uv sync` only re-runs on lockfile changes, not on
# every source edit.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY . .
RUN uv sync --locked --no-dev

EXPOSE 8000
CMD ["uv", "run", "paddock", "api"]

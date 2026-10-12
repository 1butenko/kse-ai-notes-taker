# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
WORKDIR /app

# Dev: all deps (incl. ruff/pytest), source is bind-mounted, uvicorn reloads.
FROM base AS dev
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# Prod: runtime deps only, non-root.
FROM base AS prod
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev
COPY app ./app
RUN useradd --create-home --uid 1001 app \
    && mkdir -p /data/uploads \
    && chown app /data/uploads
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Worker: the API image plus Quarto, which typesets the notes PDF with its bundled Typst.
FROM base AS typeset
ARG QUARTO_VERSION=1.10.19
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl fontconfig fonts-dejavu-core \
    && curl -fsSL -o /tmp/quarto.deb \
        "https://github.com/quarto-dev/quarto-cli/releases/download/v${QUARTO_VERSION}/quarto-${QUARTO_VERSION}-linux-$(dpkg --print-architecture).deb" \
    && apt-get install -y --no-install-recommends /tmp/quarto.deb \
    && rm -rf /tmp/quarto.deb /var/lib/apt/lists/*
# Render once so a broken Quarto or font setup fails the build, not the first notes run.
COPY <<'EOF' /tmp/warmup/warmup.qmd
---
title: "Прогрів"
lang: uk
format:
  typst:
    toc: true
    number-sections: true
    papersize: a4
    margin:
      x: 2.5cm
      y: 2.5cm
    mainfont: DejaVu Serif
    fontsize: 11pt
---
# Вступ
| Символ | Значення |
|---|---|
| $V$ | простір |

:::: {.callout-note}
## Означення
Нехай $A \in \mathbb{R}^{m \times n}$. Тоді $$\operatorname{rank} A + \dim \ker A = n.$$
::::
EOF
RUN cd /tmp/warmup && quarto render warmup.qmd --to typst && test -f warmup.pdf && rm -rf /tmp/warmup

FROM typeset AS worker-dev
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.worker.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM typeset AS worker-prod
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev
COPY app ./app
RUN useradd --create-home --uid 1001 app \
    && mkdir -p /data/uploads \
    && chown app /data/uploads
USER app
EXPOSE 8000
CMD ["uvicorn", "app.worker.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Demo hosting (Render): API and worker in one container on $PORT.
# The default stage, since Render builds the last one; keep it last.
FROM typeset AS demo
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev
COPY app ./app
COPY demo ./demo
RUN useradd --create-home --uid 1000 user \
    && mkdir -p /tmp/uploads \
    && chown user /tmp/uploads
USER user
ENV UPLOADS_DIR=/tmp/uploads WORKER_URL=http://127.0.0.1:8001 ENVIRONMENT=demo SESSIONS=true
EXPOSE 7860
CMD ["./demo/start.sh"]

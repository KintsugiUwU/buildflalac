FROM docker.io/library/python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tini \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    SOURCE_DIR=/source \
    TARGET_DIR=/target \
    CONFIG_DIR=/config \
    PORT=8090

EXPOSE 8090
VOLUME ["/config"]
HEALTHCHECK --interval=1m --timeout=10s --start-period=30s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8090\")}/health', timeout=5)"
ENTRYPOINT ["tini", "--", "docker-entrypoint.sh"]
CMD ["flalac"]

LABEL org.opencontainers.image.title="flalac" \
      org.opencontainers.image.description="Keep a lossless mirror of a music library in another format (FLAC ⇄ ALAC), with lyrics." \
      org.opencontainers.image.source="https://codeberg.org/KintsugiUwU/flalac" \
      org.opencontainers.image.licenses="GPL-3.0-or-later"

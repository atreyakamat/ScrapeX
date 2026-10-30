# syntax=docker/dockerfile:1
# Build:            docker build -t scrapex .
# With JS support:  docker build --build-arg WITH_JS=true -t scrapex:js .
# TUI:              docker run -it --rm -v "$PWD/output:/data" scrapex
# Headless:         docker run --rm -v "$PWD/output:/data" scrapex crawl https://example.com -n 100

FROM python:3.12-slim AS base

ARG WITH_JS=false
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    SCRAPEX_OUTPUT=/data \
    TERM=xterm-256color \
    COLORTERM=truecolor

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src/scrapex ./src/scrapex

RUN if [ "$WITH_JS" = "true" ]; then \
        pip install ".[js]" && playwright install --with-deps chromium; \
    else \
        pip install .; \
    fi \
    && useradd --create-home --uid 1000 scrapex \
    && mkdir -p /data && chown scrapex:scrapex /data

USER scrapex
WORKDIR /data
VOLUME ["/data"]

ENTRYPOINT ["scrapex"]
CMD ["tui"]

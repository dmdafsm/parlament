# One image for the web server and the collector (they differ only by command, see compose.yaml).
FROM ghcr.io/astral-sh/uv:0.13.5 AS uv

FROM python:3.12-slim AS app
COPY --from=uv /uv /usr/local/bin/uv
ENV TZ=Europe/Bucharest \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PARLAMENT_DATA_DIR=/data \
    PATH=/opt/venv/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 parlament && mkdir -p /data && chown parlament /data
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
USER parlament
EXPOSE 8000
CMD ["parlament", "serve", "--host", "0.0.0.0", "--port", "8000"]

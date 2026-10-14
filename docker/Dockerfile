# speakcheck server image. Build from the repository root:
#
#   docker build -f docker/Dockerfile --build-arg ACCELERATOR=cpu -t speakcheck-server:cpu .
#
# ACCELERATOR: cpu (any machine), cuda (NVIDIA, needs the NVIDIA Container Toolkit) or rocm (AMD).
# Easier: docker compose -f docker/compose.yml up -d  (see the README's "Docker" section).
FROM python:3.12-slim

ARG ACCELERATOR=cpu
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    SPEAKCHECK_HOME=/data \
    HF_HOME=/models \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# Dependencies first (cached while only the code changes).
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY plugins ./plugins
RUN uv sync --frozen --no-dev --no-install-project \
    --extra models --extra "$ACCELERATOR" --extra web --extra voice

COPY src ./src
COPY config.example.toml ./
COPY docker/config.toml ./config.toml
RUN uv sync --frozen --no-dev --extra models --extra "$ACCELERATOR" --extra web --extra voice

VOLUME ["/data", "/models"]
EXPOSE 8770
ENTRYPOINT ["speakcheck"]
CMD ["server", "serve"]

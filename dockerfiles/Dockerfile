# --- Base Stage ---
FROM python:3.12.0-slim AS base

# Install uv and system dependencies
COPY --from=ghcr.io/astral-sh/uv:0.6 /uv /uvx /bin/
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install dependencies first to optimize Docker layer caching
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Add a non-root user for security
RUN useradd -m appuser && chown -R appuser /app
USER appuser

# Set environment variables
ENV PYTHONPATH=/app/src
ENV PATH="/app/.venv/bin:$PATH"

# --- Labels ---

# Static labels (from project metadata)
LABEL org.opencontainers.image.title="teaching_load" \
      org.opencontainers.image.description="Suivi du plan de charge enseignant (Makersboard + ADE, DuckDB, Streamlit)" \
      org.opencontainers.image.authors="astrodata.co@gmail.com" \
      org.opencontainers.image.source="https://github.com/your-org/your-repo" \
      org.opencontainers.image.licenses="No license file"

# Dynamic labels (injected at build time)
ARG BUILD_VERSION="dev"
ARG BUILD_REVISION="unknown"
ARG BUILD_DATE="unknown"

LABEL org.opencontainers.image.version="${BUILD_VERSION}" \
      org.opencontainers.image.revision="${BUILD_REVISION}" \
      org.opencontainers.image.created="${BUILD_DATE}"

# --- API Stage ---
FROM base AS api

# Copy the rest of the application
COPY . .

# Healthcheck to monitor container status
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the API
CMD ["uvicorn", "teaching_load.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# --- Streamlit Stage ---
FROM base AS streamlit

# Copy the rest of the application
COPY . .

# Healthcheck to monitor container status
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Run Streamlit
CMD ["streamlit", "run", "app/streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
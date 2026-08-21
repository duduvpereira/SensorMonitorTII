# syntax=docker/dockerfile:1

# ============================================================================
# Stage 1 — builder: install dependencies into an isolated virtualenv.
# Keeping this separate means the final image doesn't carry pip, build caches,
# or the toolchain — only the runtime and the installed packages.
# ============================================================================
FROM python:3.12-slim AS builder

# Don't write .pyc files and don't buffer stdout/stderr (better container logs).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# Create a virtualenv we can copy wholesale into the final stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install only production dependencies (requirements.txt), leveraging Docker
# layer caching: this layer is rebuilt only when requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ============================================================================
# Stage 2 — runtime: minimal image with just the venv + app code.
# ============================================================================
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Copy the ready-made virtualenv from the builder stage.
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Copy the application code. Tests, docs, and dev tooling are excluded via
# .dockerignore, so the image stays lean.
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY mock_uc/ ./mock_uc/

# Run as a non-root user for safety.
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

# The app serves the web UI and the frontend<->backend WebSocket here.
EXPOSE 48000

# Bind to 0.0.0.0 so the server is reachable from outside the container.
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "48000"]

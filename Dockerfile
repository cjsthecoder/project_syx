# Syx AGI Chatbot Framework - Docker image (Ubuntu, Python 3.13.3)
# Multi-stage: Node for frontend build, Python for backend + static serving.

# ------------------------------------------------------------------------------
# Stage 1: Build React frontend (Vite) into backend/app/static
# ------------------------------------------------------------------------------
FROM node:20-bookworm-slim AS frontend-builder

WORKDIR /app

# Install frontend deps (use lockfile if present)
COPY frontend/package.json frontend/package-lock.json* ./frontend/
RUN cd frontend && npm ci 2>/dev/null || npm install

# Copy frontend source and create backend/app/static so Vite can write there
COPY frontend ./frontend
RUN mkdir -p backend/app/static

# Build; Vite writes to ../backend/app/static
RUN cd frontend && npm run build

# ------------------------------------------------------------------------------
# Stage 2: Backend (Python 3.13.3 + FastAPI) + pre-built static
# ------------------------------------------------------------------------------
FROM python:3.13.3-slim-bookworm AS backend

WORKDIR /app

# Copy backend (includes backend/app/config/route_policy.json)
COPY backend ./backend
COPY requirements.txt ./requirements.txt

# Overwrite with built static from stage 1
COPY --from=frontend-builder /app/backend/app/static ./backend/app/static

# Directories the app writes to (bind mounts override these at runtime)
RUN mkdir -p data/memory data/db runtime/logs runtime/runs runtime/state

# Build tools + Rust (numpy needs gcc; tiktoken needs Rust when no wheel for platform/python)
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
ENV PATH="/root/.cargo/bin:${PATH}"
# Let tiktoken (PyO3) build against Python 3.13 via stable ABI (PyO3 officially supports up to 3.12)
ENV PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1

# Virtualenv and install Python deps
RUN python3 -m venv /app/venv && \
    /app/venv/bin/pip install --upgrade pip setuptools wheel && \
    /app/venv/bin/pip install -r requirements.txt

# App runs from backend/ so relative paths (../data/*, ../runtime/*) resolve correctly
WORKDIR /app/backend

# .env is mounted at /app/.env at runtime (Option B); do not bake secrets into image
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD /app/venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["/app/venv/bin/python", "-m", "app.main"]

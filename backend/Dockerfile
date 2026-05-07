# ─────────────────────────────────────────────────────────────────────────────
# AMAN ERP — Backend Dockerfile
# Multi-stage build: builder (deps) → runtime (slim)
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Build dependencies ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# System build deps (psycopg2 needs libpq-dev, python-ldap needs libldap2-dev, xmlsec needs libxmlsec1-dev)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libldap2-dev \
    libsasl2-dev \
    libxmlsec1-dev \
    libxml2-dev \
    pkg-config \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps into a prefix so we can copy them cleanly
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt && \
    # Explicitly ensure email-validator is installed (required by pydantic EmailStr) \
    pip install --no-cache-dir --prefix=/install "email-validator>=2.0.0" && \
    ls /install/lib/python*/site-packages/ | grep -q email_validator && echo "✅ email-validator verified"


# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

# Runtime system deps + gosu (privilege dropping in entrypoint)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    gosu \
    libmagic1 \
    clamav-freshclam \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code (excluding .env, __pycache__, venv, etc.)
COPY . .

# Create non-root user; uploads dirs are created by entrypoint.sh at runtime
# so they are always on the live volume, not overridden by Docker mount.
RUN addgroup --system aman && adduser --system --ingroup aman aman \
    && chown -R aman:aman /app

# Entrypoint: runs as root → creates/chowns /app/uploads → drops to aman → execs CMD
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]

# Expose port
EXPOSE 8000

# Health check — Docker will restart the container if unhealthy
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start server — Gunicorn with Uvicorn workers for production
CMD ["gunicorn", "main:app", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "4", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--keep-alive", "5", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--log-level", "info"]

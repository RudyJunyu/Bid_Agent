ARG PYTHON_IMAGE=m.daocloud.io/docker.io/library/python:3.12-slim
FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/backend \
    HF_HOME=/app/.cache/huggingface \
    XDG_CACHE_HOME=/app/.cache
WORKDIR /app
COPY requirements/base.lock /tmp/base.lock
RUN pip install --no-cache-dir -r /tmp/base.lock \
    && groupadd --gid 10001 bid \
    && useradd --uid 10001 --gid bid --create-home bid \
    && mkdir -p /app/storage/data /app/storage/chroma /app/.cache \
    && chown -R bid:bid /app/storage /app/.cache
COPY --chown=bid:bid backend /app/backend
COPY --chown=bid:bid scripts/reindex.py /app/scripts/reindex.py
USER bid
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)"
CMD ["python", "-m", "uvicorn", "bid_agent.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

FROM base AS full
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libgl1 libgomp1 tesseract-ocr tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*
COPY requirements/full.lock /tmp/full.lock
RUN pip install --no-cache-dir -r /tmp/full.lock
USER bid

# Default lightweight image; target=full enables local AI dependencies.
FROM base AS runtime

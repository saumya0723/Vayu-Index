FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VAYU_HOST=0.0.0.0 \
    VAYU_PORT=8000 \
    VAYU_LIVE_COLLECTION_DIR=/var/lib/vayu/live_collection

WORKDIR /app

COPY requirements-phase14.txt ./requirements-phase14.txt
RUN python -m pip install --no-cache-dir -r requirements-phase14.txt \
    && groupadd --system --gid 10001 vayu \
    && useradd --system --uid 10001 --gid vayu --home-dir /nonexistent --shell /usr/sbin/nologin vayu \
    && mkdir -p /var/lib/vayu/live_collection \
    && chown -R vayu:vayu /var/lib/vayu

COPY --chown=vayu:vayu . /app

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os; from urllib.request import urlopen; port=os.environ.get('PORT') or os.environ.get('VAYU_PORT','8000'); urlopen(f'http://127.0.0.1:{port}/api/v1/health', timeout=4).read()" || exit 1

CMD ["python", "scripts/run_api.py"]

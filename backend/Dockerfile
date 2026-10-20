FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /w
COPY requirements.lock .
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r requirements.lock

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/opt/venv/bin:$PATH PORT=8000 NEWS_DB=/data/runs.db
RUN useradd -m -u 10001 app && mkdir /data && chown app /data
COPY --from=build /opt/venv /opt/venv
WORKDIR /srv
COPY app ./app
USER app
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'], timeout=2)"
# one process only: run state and rate limits live in memory
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1"]

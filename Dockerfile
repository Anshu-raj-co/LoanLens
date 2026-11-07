# LoanLens: one image for the REST API, the Streamlit app and the batch worker.
# The service is chosen by the command (see docker-compose.yml):
#   api:     uvicorn loanlens.api.app:app --host 0.0.0.0 --port 8000   (default)
#   app:     streamlit run app/Home.py --server.address 0.0.0.0 --server.port 8501
#   worker:  python -m loanlens.worker
#   migrate: python -m loanlens.db upgrade
# No dataset is copied: the registry, the active model artifact and the aggregates file
# for the Analytics page are enough (data/hosted/analytics_aggregates.json).

# ---- Build stage: install the pinned dependencies and the package into a virtualenv ------
FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /build
RUN python -m venv /opt/venv

COPY requirements.txt constraints.txt ./
# Same pins as requirements.txt, every indirect package pinned by constraints.txt, except
# that XGBoost comes from xgboost-cpu (the XGBoost project's CPU-only build of the same
# version, without the CUDA libraries of the Linux xgboost wheel); LoanLens never uses a GPU.
# Windows line endings are removed first. The pip cache is a build cache only.
RUN --mount=type=cache,target=/root/.cache/pip \
    sed -e 's/\r$//' -e 's/^xgboost==/xgboost-cpu==/' requirements.txt > requirements-docker.txt \
    && sed -e 's/\r$//' constraints.txt > constraints-docker.txt \
    && grep -q '^xgboost-cpu==2.1.3$' requirements-docker.txt \
    && pip install --retries 10 --timeout 120 \
       -r requirements-docker.txt -c constraints-docker.txt

COPY pyproject.toml ./
COPY src ./src
# Non-editable install of the package itself; dependencies are already pinned above.
RUN pip install --no-deps . \
    && python -c "import loanlens.db.engine as e; assert (e.MIGRATIONS_DIR / 'env.py').exists()"

# ---- Runtime stage ---------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    LOANLENS_HOME=/app \
    LOANLENS_JOBS_DIR=/data/jobs \
    LOANLENS_SERVICE=api

# A fixed non-root user; the jobs directory is created here so a named volume mounted on
# it starts out owned by that user.
RUN groupadd --system --gid 10001 loanlens \
    && useradd --system --uid 10001 --gid loanlens --create-home --home-dir /home/loanlens \
       --shell /usr/sbin/nologin loanlens \
    && mkdir -p /data/jobs \
    && chown loanlens:loanlens /data/jobs

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY config ./config
COPY models ./models
COPY data/hosted ./data/hosted
COPY reports/model_card.md ./reports/model_card.md
COPY app ./app
COPY .streamlit/config.toml ./.streamlit/config.toml
COPY alembic.ini ./

USER loanlens

EXPOSE 8000 8501

# Checks the service named by LOANLENS_SERVICE (api, app or worker).
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["python", "-m", "loanlens.healthcheck"]

CMD ["uvicorn", "loanlens.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

# One image, several roles (api, agent-worker, verifier-agent, llm-stub, indexer).
# The role is chosen by the compose `command`. Same code everywhere, separate processes.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/hf

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# CPU-only torch first, so sentence-transformers does not pull the CUDA build
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.15.0

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY agent ./agent
COPY api ./api
COPY eval ./eval
COPY frontend ./frontend
COPY ingest ./ingest
COPY loadtest ./loadtest
COPY observability ./observability
COPY stub_llm ./stub_llm
COPY verifier_service ./verifier_service
COPY data ./data
COPY .env.example ./.env.example

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/data/index /models/hf \
    && chown -R app:app /app/data /models
USER app

EXPOSE 8000
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    SEED_DIR=/app/seed \
    OUT_DIR=/app/out \
    REPLAY_LLM=true \
    CASE_ID=CEDX-B5AAC2 \
    PIPELINE_VERSION=0.4.0-step4

CMD ["python", "-m", "pipeline.run"]
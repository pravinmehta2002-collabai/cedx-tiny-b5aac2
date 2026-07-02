FROM python:3.11-slim

# System basics (for PDF parsing later)
RUN apt-get update && apt-get install -y --no-install-recommends \
        make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python deps first (better caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the code
COPY . .

# Default env
ENV PYTHONUNBUFFERED=1 \
    SEED_DIR=/app/seed \
    OUT_DIR=/app/out \
    REPLAY_LLM=true \
    CASE_ID=CEDX-B5AAC2 \
    PIPELINE_VERSION=0.1.0-tracer

# Default command: run the full demo
CMD ["make", "demo"]
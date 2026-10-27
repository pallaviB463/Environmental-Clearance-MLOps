FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application codebase
COPY . .

# Expose API port
EXPOSE 8000

# Default entrypoint starts the API and background worker
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]

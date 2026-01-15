FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for drivers if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    freetds-dev \
    freetds-bin \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install .

COPY src/ .

CMD ["python", "-m", "mcp_database.server"]

FROM python:3.11-slim

WORKDIR /app

# Copy and install requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code, migrations and scripts
COPY src /app/src
COPY migrations /app/migrations
COPY scripts /app/scripts
COPY alembic.ini /app/alembic.ini

ENV PYTHONPATH=/app/src:/app

CMD ["sh", "-c", "alembic upgrade head && uvicorn api:app --host 0.0.0.0 --port 8000"]

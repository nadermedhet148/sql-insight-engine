FROM python:3.11-slim

WORKDIR /app

# Copy and install requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src /app/src

ENV PYTHONPATH=/app/src

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]

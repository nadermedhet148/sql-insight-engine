FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install .

COPY src/ .

CMD ["python", "mcp_chroma/server.py"]

FROM python:3.11-slim

WORKDIR /app

COPY main.py .

RUN pip install fastapi uvicorn pydantic redis httpx

EXPOSE 8010

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010"]

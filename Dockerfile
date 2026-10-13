FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY engine.py .

ENV ENGINE_HOST=0.0.0.0
ENV ENGINE_PORT=8080
ENV DEFAULT_THREADS=50
ENV MAX_THREADS=500
ENV BURST_SIZE=1400
ENV LOG_LEVEL=INFO

EXPOSE 8080

CMD ["python", "engine.py"]

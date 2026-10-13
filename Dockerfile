FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY engine.py .

ENV ENGINE_HOST=0.0.0.0
ENV ENGINE_PORT=8080

EXPOSE 8080

CMD ["python", "engine.py"]

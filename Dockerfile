FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=America/Fortaleza
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mnia ./mnia
COPY config ./config

RUN useradd -m mnia && mkdir -p /app/dados && chown -R mnia /app
USER mnia

CMD ["python", "-m", "mnia", "rodar"]

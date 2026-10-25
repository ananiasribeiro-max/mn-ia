FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=America/Fortaleza
WORKDIR /app

# ffmpeg para os cortes de vídeo; fontes para título e legenda nos cortes;
# nodejs para o yt-dlp resolver os desafios de JavaScript do YouTube
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mnia ./mnia
COPY config ./config
COPY assets ./assets

RUN useradd -m mnia && mkdir -p /app/dados && chown -R mnia /app
USER mnia

CMD ["python", "-m", "mnia", "rodar"]

FROM python:3.12-slim

ARG GIT_HASH=unknown
ARG BUILD_DATE=unknown
ENV BOT_GIT_HASH=$GIT_HASH
ENV BOT_BUILD_DATE=$BUILD_DATE

RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata docker.io \
    ffmpeg libopus0 libopus-dev libffi-dev git \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 wally
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/
COPY scripts/ ./scripts/
# L'extension musique : servie en .zip par le bot, pour installation chez Azraël.
COPY extension-musique/ ./extension-musique/
# Lu par `bot/dashboard/routes/roadmap.py` (`parents[3]` → /app). Absent de
# l'image, l'endpoint répondait 200 avec zéro section depuis toujours. Le
# `.dockerignore` n'y suffisait pas : rien ne copiait le fichier.
COPY ROADMAP.md ./

RUN mkdir -p /app/data /app/logs && chown -R wally:wally /app

USER wally

CMD ["python", "-m", "bot.main"]

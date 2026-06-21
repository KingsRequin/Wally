FROM python:3.12-slim

ARG GIT_HASH=unknown
ARG BUILD_DATE=unknown
ENV BOT_GIT_HASH=$GIT_HASH
ENV BOT_BUILD_DATE=$BUILD_DATE

RUN apt-get update && apt-get install -y --no-install-recommends tzdata docker.io && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 wally
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/
COPY scripts/ ./scripts/

RUN mkdir -p /app/data /app/logs && chown -R wally:wally /app

USER wally

CMD ["python", "-m", "bot.main"]

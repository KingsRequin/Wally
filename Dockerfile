FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata docker.io \
    ffmpeg libopus0 libopus-dev libffi-dev git \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 wally
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Version du build ──────────────────────────────────────────────────────────
# PLACÉ ICI, PAS EN HAUT DU FICHIER. Un `ENV` qui change invalide TOUTES les
# couches en dessous de lui. `BUILD_DATE` est un timestamp à la seconde : il
# change par construction à chaque build. Déclarés avant `apt-get`/`pip`, ces
# deux ENV garantissaient donc une réinstallation complète de ffmpeg, opus et
# des 59 dépendances Python à CHAQUE rebuild — mesuré le 2026-08-20 :
# 110 s de build (apt 32 s + pip 34 s + export 63 s) pour changer une ligne de
# Python, contre 3,3 s une fois les ARG descendus sous les couches lourdes.
# Vérification : deux builds d'affilée avec des GIT_HASH DIFFÉRENTS doivent
# afficher `CACHED` sur les étapes apt-get et pip install.
# Ne jamais les remonter : la seule chose qui doit invalider le cache ici,
# c'est le code lui-même, copié juste en dessous.
ARG GIT_HASH=unknown
ARG BUILD_DATE=unknown
ENV BOT_GIT_HASH=$GIT_HASH
ENV BOT_BUILD_DATE=$BUILD_DATE

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

# Almeida-only build: no browser needed, so a slim Python image (tiny + low RAM).
# To re-enable the browser adapters (National Theatre / Royal Court), switch the
# base image back to mcr.microsoft.com/playwright/python:v1.47.0-jammy and add
# `playwright==1.47.0` to requirements.txt.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot
COPY scripts ./scripts

# SQLite lives here; mount a volume so monitors survive restarts.
ENV DB_PATH=/data/monitors.db
VOLUME ["/data"]

CMD ["python", "-m", "bot.main"]

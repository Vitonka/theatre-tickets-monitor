# Playwright's own image ships a matching Chromium + all system libraries,
# so we never run `playwright install` and never hit browser/version drift.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot

# SQLite lives here; mount a volume so monitors survive restarts.
ENV DB_PATH=/data/monitors.db
VOLUME ["/data"]

CMD ["python", "-m", "bot.main"]

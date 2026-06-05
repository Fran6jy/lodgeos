# LodgeOS — single image, runs either the bot or the dashboard (command set in compose).
FROM python:3.12-slim

# libgomp1 is required by ctranslate2 (faster-whisper). Everything else (PyAV for
# audio decode, matplotlib fonts) ships in the wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY openclaw ./openclaw

ENV PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/mpl

# Default command (compose overrides per service).
CMD ["python", "-m", "openclaw.integrations.telegram_bot.bot"]

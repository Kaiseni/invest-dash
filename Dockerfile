FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY run.py .

# Compte sans privilèges ; /app/data (base chiffrée) est un volume persistant
RUN useradd --system --uid 10001 --no-create-home app \
    && mkdir -p /app/data && chown -R app:app /app/data
USER app
VOLUME /app/data
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/auth/status', timeout=4)" || exit 1

# UN SEUL worker (+ threads) : les clés de chiffrement des sessions vivent en mémoire de ce processus.
CMD ["gunicorn", "-w", "1", "--threads", "4", "--timeout", "120", "-b", "0.0.0.0:5000", "run:app"]

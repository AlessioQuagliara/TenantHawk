# =============================================================================
# backend/Dockerfile
# =============================================================================

# Base immagine leggera di python
FROM python:3.11-slim

# Evita creazione di file binari strani
ENV PYTHONDONTWRITEBYTECODE=1

# Evita buffering
ENV PYTHONUNBUFFERED=1

# Prende la directory /app per i comandi
WORKDIR /app

# requirements.txt da installare all'avvio
COPY requirements.txt /app/

# Installazione curl su server
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r requirements.txt

# Copia solo la cartella /app senza copiare .venv o requirements.txt
COPY app /app/app

# Copia Alembic per far funzionare le migrazioni
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic

# Esponi su porta 8000
EXPOSE 8000

# Settaggio con Gunicorn gestisce i worker, UvicornWorker gestisce l'async per ciascuno
CMD ["sh", "-c", "gunicorn app.main:app --workers ${APP_WORKERS:-4} --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --timeout 120 --graceful-timeout 30 --keep-alive 5 --max-requests 1000 --max-requests-jitter 100 --access-logfile - --error-logfile -"]

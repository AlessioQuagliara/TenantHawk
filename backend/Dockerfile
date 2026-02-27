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


RUN pip install --no-cache-dir -r requirements.txt

# Copia solo la cartella /app senza copiare .venv o requirements.txt
COPY app /app/app

# Esponi su porta 8000
EXPOSE 8000

# Settaggio Uvicorn async, PER ORA CON RELOAD DEV (DA TOGLIERE IN PROD)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
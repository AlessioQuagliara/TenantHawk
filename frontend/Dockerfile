# =============================================================================
# frontend/Dockerfile
# =============================================================================

# Base immagine leggera di Node
FROM node:20-slim

# Prende la directory /app per i comandi
WORKDIR /app

# package.json da installare all'avvio
COPY package.json package-lock.json* ./

RUN npm ci --include=optional \
    && npm rebuild lightningcss

# Copia solo il resto del codice senza copiare node_modules
COPY . .

# Esponi su porta 3000
EXPOSE 3000

# Settaggio npm, PER ORA CON DEV (DA TOGLIERE IN PROD)
CMD ["npm", "run", "dev"]
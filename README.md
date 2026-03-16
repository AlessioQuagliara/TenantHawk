<!-- Licenza -->
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

<!-- GitHub -->
[![GitHub Repo](https://img.shields.io/badge/GitHub-000000?style=for-the-badge&logo=github&logoColor=white)](https://github.com/user/repo) ![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white) ![n8n](https://img.shields.io/badge/n8n-1EC19A?style=for-the-badge&logo=n8n&logoColor=white) ![Traefik](https://img.shields.io/badge/Traefik-24A1C1?style=for-the-badge&logo=traefikproxy&logoColor=white) ![LiteLLM](https://img.shields.io/badge/LiteLLM-4B32C3?style=for-the-badge&logo=python&logoColor=white) ![Next.js](https://img.shields.io/badge/Next.js-000000?style=flat&logo=next.js&logoColor=white) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white) ![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
****
![Logo](/img/logo.gif)
****
# SaaS Template
## ..........Crea velocemente il tuo SaaS!
### .....................Completo di tutto
#### .........................................Deploy veloce
##### .......................................................................Scalabilità verticale
###### ..............................................................................Multitenant, Automazioni, LLM... TUTTO!

**Crea il tuo SaaS con uno stack moderno ed affidabile**.

****

### Avvio Progetto

![Terminale](/img/terminal.gif)

Avviare il progetto è molto semplice, ti basta entrare con un terminale sulla cartella del progetto e digitare ```docker compose up --build``` per avviare il tutto!

> **Raccomandazioni**: Creare un file .env con tutte le variabili del caso, questa spiegazione si lascia al fondo del foglio.

Prima di creare il progetto si raccomanda di avviare le migrazioni con **alembic**, tramite il comando ```docker compose exec backend alembic revision --autogenerate -m "Inizializza"```, dopodiché consiglio il comando per applicare le migrazioni: ```docker compose exec backend alembic upgrade head```, questo per poter partire subito.

Quindi:
1) Step
```bash
docker compose exec backend alembic revision --autogenerate -m "Inizializza"
```
2) Step
```bash
docker compose exec backend alembic upgrade head
```

Se si vuole creare un utente manualmente senza usare la registrazione di admin.localhost si può tramite seed, che ha il comando:
```bash
docker compose exec backend python -m app.cli seed tenant-admin \
  --slug demo \
  --nome-tenant "Tenant Demo" \
  --admin-email admin@demo.com \
  --admin-password latuapassword
```
è importante notare che questo comando non agisce sul ruolo tenant, quindi questo utente ne sarà sprovvisto.

### Monitoring risorse
![Docker](/img/docker.gif)

Anche se non l'ho detto, per lo sviluppo è importante possedere l'applicazione di ```docker```, senza di essa non potrete usare comandi come: ```docker compose up``` per avviare il progetto.

Con essa potrete vedere i logs, monitorare le risorse, e vedere i container se sono attivi o meno.

I comandi principali che userete sono:
```bash
docker compose up -d
```
*Esso avvia l'applicativo*
```bash
docker compose down
```
*Questo spegne i container preservando i dati su DB e altro*

**ATTENZIONE**: Non avviare mai in produzione il comando ```docker compose down -v```, poiché esso **cancellerà anche tutti i dati del database** senza fare eccezioni, poi sarà tutto irrecuperabile.

```bash
docker compose build
```
Per fare la build di eventuali modifiche, utile prima dell'avvio, per casi disperati usare ```docker compose build --no-cache```, serve per buildare senza residui di cache.
```bash
docker compose up --build
```
Molto utile, avvia e builda allo stesso tempo. 

### Admin - Backend
![Admin](/img/admin.gif)
### Landing - Frontend
![Landing](/img/frontend.gif)
### Traefik - Reverse Proxy
![Traefik](/img/traefik.gif)
### LiteLLM - Gestione LLM
![LiteLLM](/img/litellm.gif)
### n8n - Creazione Automazioni
![n8n](/img/n8n.gif)

****

### Licenza MIT
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
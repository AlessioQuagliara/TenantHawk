
![Logo](backend/app/static/images/logo-dark.svg)


---


> Template open source per SaaS multi-tenant con costruttore di moduli integrato.


Stack: FastAPI async + SQLAlchemy 2 + asyncpg + Jinja2/HTMX per il backend, Next.js 16 con Tailwind per il frontend, Docker Compose + Traefik + Postgres per l'infrastruttura.


## Caratteristiche


- Routing admin multi-tenant via path: `/{tenant}/admin/...`
- Autenticazione reale con bcrypt async, cookie di sessione e isolamento per tenant
- Admin HTML (Jinja2 + HTMX) con componenti personalizzabili
- Landing marketing in Next.js
- Postgres con engine async, connection pooling calibrato per worker
- Reverse proxy Traefik pronto per HTTPS (Let's Encrypt) in produzione
- Migrazioni database con Alembic (async, autogenerate)
- CLI di scaffolding per generare moduli backend in pochi secondi
- Gunicorn + UvicornWorker per produzione stabile con restart automatico dei worker
- Healthcheck integrato per Docker


## Struttura


- `backend/`: FastAPI, template Jinja2/HTMX, modelli SQLAlchemy, migrazioni Alembic, CLI
- `frontend/`: Next.js landing
- `compose.yaml`: stack completo (Traefik, Postgres, backend, frontend)
- `test/`: script k6 per load testing


## Autenticazione e multi-tenancy


Il login è su `admin.localhost` (senza prefisso tenant) e risolve automaticamente il tenant dell'utente dal database. Dopo il login il browser viene reindirizzato a `/{tenant}/admin/dashboard`. Ogni area admin è isolata per tenant tramite dependency FastAPI che verifica slug, stato attivo e appartenenza dell'utente.


## Migrazioni e seed


Le migrazioni si gestiscono con Alembic direttamente nel container backend:

```bash
# Genera una nuova migrazione dopo aver modificato i modelli
docker compose exec backend alembic revision --autogenerate -m "descrizione"

# Applica le migrazioni
docker compose exec backend alembic upgrade head

# Crea un tenant e il suo utente admin iniziale
docker compose exec backend python -m app.cli seed tenant-admin \
  --slug demo \
  --nome-tenant "Tenant Demo" \
  --admin-email admin@demo.com \
  --admin-password latuapassword
```


## Costruttore moduli


La CLI permette di generare moduli backend completi senza scrivere boilerplate:

```bash
# Lista comandi disponibili per l'area admin
python -m app.cli admin --help

# Crea un modulo con rotta e template Jinja2
python -m app.cli admin create-module statistiche

# Crea un modulo completo con rotta, template, model SQLAlchemy e schema Pydantic
python -m app.cli admin create-module statistiche --with-model --with-schema
```

Ogni comando aggiorna automaticamente gli `__init__.py` coinvolti, quindi il modulo è subito disponibile senza toccare nulla a mano.


## Avvio locale


```bash
docker compose up --build
```

Admin: http://admin.localhost:8000/auth/login

Landing: http://www.localhost:3000


## Performance


Testato con k6 a 500 utenti virtuali concorrenti su MacBook con Docker:

- 929 req/s
- latenza media 28ms
- p(95) 82ms
- 0% errori

La verifica password usa bcrypt async con semaphore per non bloccare l'event loop sotto carico.


## License


MIT


***

Comandi per caricare su git:

```bash
git add README.md
git commit -m "docs: aggiorna README con auth, Alembic, CLI seed, performance e note produzione"
git push origin main
```
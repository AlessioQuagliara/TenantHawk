![Logo](backend/app/static/images/logo-dark.svg)

---

> Template open source per SaaS multi-tenant con costruttore di moduli integrato.

Stack: FastAPI async + SQLAlchemy 2 + asyncpg + Jinja2/HTMX per il backend, Next.js 16 con Tailwind per il frontend, Docker Compose + Traefik + Postgres + Redis per l'infrastruttura.

## Caratteristiche

- Routing admin multi-tenant via path: `/{tenant}/admin/...`
- Autenticazione sicura con Redis session store, CSRF protection e bcrypt async
- Sistema ruoli granulare per-tenant (un utente può essere admin in un tenant e viewer in un altro)
- Password recovery funzionante con token temporanei firmati
- Admin HTML (Jinja2 + HTMX) con componenti personalizzabili
- Landing marketing in Next.js
- Postgres con engine async, connection pooling calibrato per worker
- Redis per sessioni distribuite (scalabile orizzontalmente)
- Reverse proxy Traefik pronto per HTTPS (Let's Encrypt) in produzione
- Migrazioni database con Alembic (async, autogenerate)
- CLI di scaffolding per generare moduli backend in pochi secondi
- Gunicorn + UvicornWorker per produzione stabile con restart automatico dei worker
- Healthcheck integrato per Docker

## Struttura

- `backend/`: FastAPI, template Jinja2/HTMX, modelli SQLAlchemy, migrazioni Alembic, CLI
- `frontend/`: Next.js landing
- `compose.yaml`: stack completo (Traefik, Postgres, Redis, backend, frontend)
- `test/`: script k6 per load testing

## Autenticazione e sicurezza

Il login è su `admin.localhost` (senza prefisso tenant) e risolve automaticamente il tenant dell'utente dal database. Dopo il login il browser viene reindirizzato a `/{tenant}/admin/dashboard`. 

**Sicurezza implementata:**
- Sessioni server-side in Redis (non manipolabili dal client)
- Cookie HTTP-only con SameSite=Lax
- CSRF token firmato con scadenza su ogni form
- Password hashing con bcrypt async (non blocca l'event loop)
- Token temporanei per password recovery (validi 1 ora)
- Sistema ruoli per-tenant con check granulari

Ogni area admin è isolata per tenant tramite dependency FastAPI che verifica slug, stato attivo e appartenenza dell'utente. Le sessioni scadono dopo 24h di inattività e vengono invalidate al logout.

## Sistema ruoli

Gli utenti hanno ruoli diversi per ogni tenant tramite la tabella `utente_ruolo_tenant`:

- **SUPERUTENTE**: accesso completo, può gestire altri utenti
- **COLLABORATORE**: può creare e modificare contenuti
- **MODERATORE**: può moderare contenuti ma non eliminarli
- **UTENTE**: solo lettura

Esempio: Mario può essere SUPERUTENTE in "Azienda A" e UTENTE in "Azienda B".

Per proteggere route admin:

```python
from app.core.permessi import richiede_ruolo, solo_superutente
from app.models import UtenteRuolo

@router.get("/users")
async def lista_utenti(
    _: None = Depends(richiede_ruolo([UtenteRuolo.SUPERUTENTE, UtenteRuolo.COLLABORATORE]))
):
    # Solo SUPERUTENTE e COLLABORATORE possono accedere
    ...

@router.delete("/users/{id}")
async def elimina_utente(
    id: int,
    _: None = Depends(solo_superutente),
):
    # Solo SUPERUTENTE può eliminare
    ...
```

## Migrazioni e seed

Le migrazioni si gestiscono con Alembic direttamente nel container backend:

```bash
# Genera una nuova migrazione dopo aver modificato i modelli
docker compose exec backend alembic revision --autogenerate -m "descrizione"

# Applica le migrazioni
docker compose exec backend alembic upgrade head

# Crea un tenant, utente admin e assegna ruolo SUPERUTENTE
docker compose exec backend python -m app.cli seed tenant-admin \
  --slug demo \
  --nome-tenant "Tenant Demo" \
  --admin-email admin@demo.com \
  --admin-password latuapassword
```

Lo script seed è idempotente: se tenant o utente esistono già non fallisce e mostra un messaggio info.

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

Testato con k6 a 700 utenti virtuali concorrenti (con CSRF + Redis) su MacBook con Docker:

- **95.6 req/s HTTP** (`4152` richieste totali)
- **31.9 login completi/secondo** (`1384` iterazioni completate)
- **0% errori** su `4152` richieste e `1384` iterazioni
- **Latenza media 6.39s** (`p90 15.13s`, `p95 17.41s`) sotto stress estremo a `700 VU`
- Ogni login completo esegue 3 richieste (GET form CSRF, POST login, GET dashboard)

La verifica password usa bcrypt async con semaphore per non bloccare l'event loop sotto carico. Redis gestisce tutte le sessioni senza problemi anche con migliaia di utenti concorrenti.

```bash


         /\      Grafana   /‾‾/
    /\  /  \     |\  __   /  /
   /  \/    \    | |/ /  /   ‾‾\
  /          \   |   (  |  (‾)  |
 / __________ \  |_|\_\  \_____/


     execution: local
        script: test/test_login.js
        output: -

     scenarios: (100.00%) 1 scenario, 700 max VUs, 1m0s max duration (incl. graceful stop):
              * default: 700 looping VUs for 30s (gracefulStop: 30s)



  █ TOTAL RESULTS

    checks_total.......: 9688    223.040847/s
    checks_succeeded...: 100.00% 9688 out of 9688
    checks_failed......: 0.00%   0 out of 9688

    ✓ login page status è 200
    ✓ login status è 303
    ✓ header Location presente
    ✓ cookie id_sessione_utente impostato
    ✓ dashboard status è 200
    ✓ dashboard contiene HTML
    ✓ dashboard non ha errore sessione

    HTTP
    http_req_duration..............: avg=6.39s min=896µs med=4.92s max=26.27s p(90)=15.13s p(95)=17.41s
      { expected_response:true }...: avg=6.39s min=896µs med=4.92s max=26.27s p(90)=15.13s p(95)=17.41s
    http_req_failed................: 0.00%  0 out of 4152
    http_reqs......................: 4152   95.588934/s

    EXECUTION
    iteration_duration.............: avg=20.2s min=1.9s  med=19s   max=42.56s p(90)=25.65s p(95)=27.05s
    iterations.....................: 1384   31.862978/s
    vus............................: 92     min=92        max=700
    vus_max........................: 700    min=700       max=700

    NETWORK
    data_received..................: 46 MB  1.1 MB/s
    data_sent......................: 899 kB 21 kB/s




running (0m43.4s), 000/700 VUs, 1384 complete and 0 interrupted iterations
```

## Password recovery

Il flusso di reset password è incopleto, manca la config con una vera mail send, ma per ora:

1. Utente va su `/auth/password-recovery` e inserisce email
2. Backend genera token sicuro (valido 1 ora) e lo salva in DB
3. In dev il link viene mostrato nei log backend,  dopo l'implementazione verrà inviato via email
4. Utente clicca link con token e imposta nuova password
5. Token viene marcato come usato e non può essere riutilizzato

Per vedere il link reset in sviluppo:

```bash
docker compose logs backend | grep "Reset token"
# Output: 📧 Link: http://admin.localhost:8000/auth/reset-password?token=...
```

## Prossimi step (opzionali)

- Rate limiting login (slowapi per 5 tentativi/minuto)
- 2FA opzionale con TOTP per admin
- Email transazionali async (Celery + Redis o FastAPI BackgroundTasks)
- Session fingerprinting (IP + User-Agent hash per prevenire hijacking)
- Password policy configurabile (lunghezza min, complessità, storia)

Il template è già production-ready al 90%, questi sono miglioramenti per casi d'uso specifici.

## License

MIT

***

[![GitHub Repo](https://img.shields.io/badge/GitHub-000000?style=for-the-badge&logo=github&logoColor=white)](https://github.com/user/repo) ![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white) ![Stripe](https://img.shields.io/badge/Stripe-635BFF?style=for-the-badge&logo=stripe&logoColor=white) ![n8n](https://img.shields.io/badge/n8n-1EC19A?style=for-the-badge&logo=n8n&logoColor=white) ![Traefik](https://img.shields.io/badge/Traefik-24A1C1?style=for-the-badge&logo=traefikproxy&logoColor=white) ![LiteLLM](https://img.shields.io/badge/LiteLLM-4B32C3?style=for-the-badge&logo=python&logoColor=white) ![Next.js](https://img.shields.io/badge/Next.js-000000?style=flat&logo=next.js&logoColor=white) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white) ![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
****
![Logo](/img/logo.gif)
****
# SaaS Template v0.1
Costruisci SaaS multi-tenant production-ready senza impazzire tra frontend e backend separati.

Backend + Admin + Infra già pronti: parti subito, non tra 3 settimane.

**Crea il tuo SaaS con uno stack moderno ed affidabile**.

****

### Indice

- [Avvio Progetto](#avvio-progetto)
- [Monitoring risorse](#monitoring-risorse)
- [Backend](#backend)
- [Admin - Backend](#admin---backend)
- [Landing - Frontend](#landing---frontend)
- [Traefik - Reverse Proxy](#traefik---reverse-proxy)
- [LiteLLM - Gestione LLM](#litellm---gestione-llm)
- [Stripe - Billing e Webhook](#stripe---billing-e-webhook)
- [n8n - Creazione Automazioni](#n8n---creazione-automazioni)
- [CLI - Scaffolding Rapido](#cli---scaffolding-rapido)
- [Test Performance k6](#test-performance-k6)
- [Perché questo template](#perché-questo-template)
- [Quando usarlo](#quando-usarlo)
- [Licenza MIT](#licenza-mit)


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
Questo comando crea tenant, utente admin e assegna anche il ruolo **SUPERUTENTE** su quel tenant, quindi è perfetto per partire subito senza passare dalla registrazione iniziale.

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

### Backend
![Backend](/img/backend.gif)

Il backend è costruito con ``FastAPI`` in modalità **asincrona**, con ``SQLAlchemy async`` per il database ``PostgreSQL`` e ``Redis`` per la gestione delle **sessioni server-side**.

La logica è pensata per **SaaS multi-tenant**: ogni richiesta admin lavora sul *tenant corrente* (slug nel path) e i permessi sono gestiti con ruoli per-tenant (superutente, collaboratore, moderatore, utente).

Sul piano sicurezza include autenticazione con cookie **httpOnly**, protezione ``CSRF`` nei form auth, **hashing** password con ``bcrypt``, conferma account via email e flusso completo di reset password grazie all'integrazione di ``Resend``.

A livello architetturale unisce API + rendering server-side: ``FastAPI`` gestisce rotte, dipendenze e validazioni, mentre ``Jinja2``/``HTMX`` copre la parte interfaccia admin senza trasformare tutto in SPA.

Inoltre c'è una gestione errori centralizzata (template `HTML` o `JSON` in base alla richiesta), healthcheck dedicato e supporto ``CLI`` sia per il ``seed`` iniziale tenant/admin sia per generare nuovi moduli admin in pochi secondi.

In sintesi: backend pensato per partire subito in locale, ma con fondamenta già pronte per scalare in produzione (multi-tenant, sessioni **robuste**, **separazione ruoli**, billing e webhook già impostati).


### Admin - Backend
![Admin](/img/admin.gif)
Il lato admin è una combinazione efficiente di template server-side (Jinja2/TemplateResponse) con HTMX, abbinata a protezione CSRF nei flussi auth e a sessioni semplici ma sicure.

Inoltre il backend sfrutta componenti asincrone (asyncio) e include anche un semaphore nelle operazioni di sicurezza (bcrypt), così da mantenere buone prestazioni sotto carico. 

La scelta è quindi ricaduta su Jinja + HTMX per ridurre il Fetch Hell delle SPA complesse.

### Landing - Frontend
![Landing](/img/frontend.gif)

Il lato frontend è usato volutamente come landing, quindi orientato solo alla parte marketing, con predisposizione API per eventuali estensioni future senza appesantire l'architettura iniziale.

La scelta è ricaduta su Next.js perché consente rendering ottimizzato e una SEO più efficiente già in fase di setup.

Per stabilità, al momento Turbopack è disabilitato a causa di problematiche riscontrate con gli ultimi aggiornamenti di sicurezza.

### Traefik - Reverse Proxy
![Traefik](/img/traefik.gif)

Traefik in questo progetto fa da regista unico del traffico: invece di ricordarti porte diverse, usi host dedicati e lui smista tutto al container corretto.

In locale è configurato in `HTTP` (porta 80) per sviluppo rapido, con dashboard attiva sulla porta `8080` per controllare router e servizi in tempo reale.

Nel concreto:
- `admin.localhost` punta al backend admin (`Jinja2`/`HTMX`)
- `www.localhost` punta al frontend Next.js (landing)
- `litellm.localhost` punta al servizio LiteLLM
- `n8n.localhost` punta a n8n

Sono già presenti anche i router di produzione (`admin.linkbay-cms.com` e `www.linkbay-cms.com`), mentre la parte HTTPS/TLS è volutamente commentata perché il template nasce in modalità sviluppo e test.

Quando vorrai andare in produzione, ti basta attivare i blocchi TLS già preparati (entrypoint `websecure` + certresolver) senza dover riscrivere da zero la configurazione.

``` RICORDARSI DI METTERE UNA PROTEZIONE PER LA DASHBOARD DI TRAEFIK IN PRODUZIONE ```

### LiteLLM - Gestione LLM
![LiteLLM](/img/litellm.gif)

**LiteLLM** in questo progetto fa da proxy tra n8n e i provider LLM reali. In pratica, invece di mettere credenziali DeepSeek (o OpenAI, Anthropic, ecc.) direttamente dentro n8n, tutte le chiamate passano prima da LiteLLM e poi vengono inoltrate al provider scelto.

Perché l'ho inserito, in modo molto pratico:

- **Endpoint OpenAI-compatible**: n8n conosce già il formato OpenAI, quindi usi il nodo OpenAI nativo puntando a http://litellm:4000 senza creare nodi HTTP custom per ogni provider.
- **Switch provider senza toccare n8n**: se domani DeepSeek ha problemi o vuoi passare a Claude, modifichi una riga in ```litellm_config.yaml``` e i workflow restano invariati.
- **Gestione GDPR**: se un cliente enterprise richiede che i dati restino in EU, fai lo switch provider dal file yaml senza riscrivere flussi o automazioni.
- **Usage tracking per tenant**: LiteLLM traccia token e richieste per chiave virtuale, che è la base per il billing a consumo da implementare nel SaaS.

### Stripe - Billing e Webhook
![Stripe](/img/stripe.svg)

**Stripe** qui non è un pezzo da aggiungere dopo: è già dentro al backend ed è pensato per reggere tutta la parte billing del SaaS.

In pratica gestisce checkout, sincronizzazione delle sottoscrizioni, rinnovi, pagamenti riusciti o falliti e aggiornamento stato piano direttamente nel cuore dell'applicazione.

Questo significa una cosa molto semplice: se il tuo SaaS deve vendere piani, trial e rinnovi, la base è già pronta e non devi demandare questa logica a tool esterni.

Dentro ci sono già:

- **Webhook Stripe** per ricevere gli eventi reali e allineare il database senza passaggi manuali.
- **Billing multi-tenant** così ogni tenant mantiene il suo stato sottoscrizione in modo separato e pulito.
- **Sync stato piano** per tenere coerenti checkout, rinnovi, cancellazioni e pagamenti falliti.
- **Notifiche email** sugli eventi di abbonamento più importanti, così non resta tutto chiuso dentro Stripe.

In altre parole: n8n può orchestrare automazioni attorno al business, ma la parte economica del SaaS è già prevista nel backend, che è esattamente dove conviene tenerla.

### n8n - Creazione Automazioni
![n8n](/img/n8n.gif)

n8n in questo progetto **è il motore di automazione** e orchestrazione workflow in self-hosted dentro lo stack Docker.

L'idea è usarlo per **costruire agenti AI e workflow che interagiscono con le API del backend** FastAPI: onboarding tenant, notifiche, CRM interno, automazioni operative e flussi personalizzati.

Importante però: **n8n non serve per gestire Stripe**, perché billing, webhook e sincronizzazione sottoscrizioni sono già inclusi nel backend. Qui n8n entra in gioco come livello di automazione sopra il prodotto, non come sostituto della logica core.

Si **integra con LiteLLM tramite nodo OpenAI** nativo, quindi l'agente può chiamare DeepSeek (o altri provider) e **contemporaneamente** fare richieste HTTP verso il backend.

**Problemi** che ho (e come li ho risolti):

1. **Rete internal non definita**:
Il compose iniziale metteva n8n e LiteLLM su una rete internal non dichiarata nel blocco networks.
Soluzione: spostati entrambi sulla rete web già esistente.

2. **Encryption key mismatch**:
Al primo avvio senza N8N_ENCRYPTION_KEY, n8n genera una chiave random e la salva nel volume n8n_data.
Quando poi aggiungi la variabile nel compose, la chiave salvata nel volume può non combaciare con quella del file env.
Soluzione: ripartenza pulita eliminando il volume n8n.

```bash
docker compose down
```
```bash
docker volume rm saas_template_n8n_data
```
```bash
docker compose up -d
```

3. **Header X-Forwarded-For con Traefik**:
Traefik aggiunge X-Forwarded-For alle richieste, ma n8n di default non si fida dei proxy e il rate limiter di Express può andare in errore.
Soluzione: aggiungere N8N_TRUST_PROXY=true.

4. **Account owner al primo avvio**:
n8n non ha credenziali predefinite: al primo avvio devi creare l'account owner dalla UI su http://n8n.localhost.
Le variabili N8N_BASIC_AUTH_* sono deprecate nelle versioni recenti.

**Configurarlo in un altro ambiente:**

*Variabile minima nel file* .env:

```text
APP_N8N_ENCRYPTION_KEY=sk-oppure-stringa-random-32char
```

*Generazione chiave* (da terminale):

```bash
openssl rand -hex 32
```

*Servizio n8n nel compose* (base):

```yaml
n8n:
  image: n8nio/n8n
  environment:
    - N8N_ENCRYPTION_KEY=${APP_N8N_ENCRYPTION_KEY}
    - N8N_SECURE_COOKIE=false
    - N8N_TRUST_PROXY=true
  volumes:
    - n8n_data:/home/node/.n8n
  networks:
    - web
  labels:
    - "traefik.enable=true"
    - "traefik.http.routers.n8n.rule=Host(`n8n.localhost`)"
    - "traefik.http.routers.n8n.entrypoints=web"
    - "traefik.http.services.n8n.loadbalancer.server.port=5678"
```

Al primo avvio vai su http://n8n.localhost, crei l'account owner e attivi la licenza community da Settings -> Usage con la chiave ricevuta via email.

Importante: conserva sempre N8N_ENCRYPTION_KEY. Se la perdi o la cambi con dati già presenti nel volume, n8n non riesce più a decifrare le credenziali salvate e devi ripartire da zero.

### CLI - Scaffolding Rapido
La ``CLI`` è pensata per toglierti attrito quando inizi a far crescere il progetto: invece di creare a mano sempre gli stessi pezzi, puoi generare la base e poi rifinirla tu.

Oltre al seed iniziale tenant/admin, il backend include anche un comando per creare nuovi moduli admin in modo molto rapido.

Esempio pratico:

```bash
docker compose exec backend python -m app.cli admin create-module statistiche --with-model --with-schema
```

Cosa puoi fare:
1) Zero attrito: bootstrap completo in 1 riga
```
docker compose exec backend python -m app.cli quickstart \
  --tenant demo \
  --nome-tenant "Tenant Demo" \
  --admin-email admin@demo.com \
  --admin-password "Password123!"
```
2) Seed avanzato (controllo totale)
```
docker compose exec backend python -m app.cli seed tenant-admin \
  --slug azienda-x \
  --nome-tenant "Azienda X" \
  --admin-name "Founder Admin" \
  --admin-email founder@aziendax.it \
  --admin-password "Password123!" \
  --with-trial \
  --trial-days 14
```
3) Crea un modulo admin pronto produzione
```
docker compose exec backend python -m app.cli admin create-module ordini-vendite \
  --label "Ordini Vendite" \
  --superuser-only \
  --with-model \
  --with-schema
```
4) Vedi subito i moduli admin presenti
```
docker compose exec backend python -m app.cli admin list-modules
```


Con questo comando il template ti prepara già:

- route admin dedicata;
- cartella template con pagina iniziale;
- aggiornamento automatico del router admin;
- model SQLAlchemy opzionale;
- schema Pydantic opzionale.

Questa parte è molto comoda quando devi aggiungere sezioni come ordini, clienti, report, ticket o qualsiasi modulo interno senza ripartire da zero ogni volta.

In pratica non è una CLI "magica", ma una scorciatoia utile: ti evita lavoro ripetitivo e ti lascia subito una struttura pulita da completare.

### Test Performance k6
![k6](/img/k6.gif)

Per testare il flusso login sotto carico ho usato k6 con lo script presente in ```test/test_login.js```.

Si avvia direttamente da terminale con:

```bash
k6 run test/test_login.js
```

Questo test simula fino a 700 VUs per 30 secondi e verifica tutto il percorso:
- pagina login raggiungibile
- POST login con redirect corretto
- cookie di sessione impostato
- accesso dashboard valido dopo autenticazione

Risultato pratico del run:
- checks riusciti al 99.92% (12267 su 12276)
- errori minimi (9 check falliti su oltre 12k)
- nessun HTTP failed (0 su 5262 richieste)

Nel test sono comparsi alcuni errori "Cookie sessione non impostato dopo login" solo su una piccola percentuale di richieste ad alto carico. 

Quindi il sistema regge bene, ma vale la pena continuare a monitorare il punto sessione/cookie quando si spinge verso concorrenze molto alte.

>**In sintesi:** benchmark **positivo**, stack **stabile** anche con **stress importante**, con piccoli edge case da tenere sotto osservazione nei picchi.

****

### Perché questo template

- Niente fetch hell tra frontend e backend;
- Multi-tenant già risolto (non banale);
- auth + sicurezza già production-ready;
- billing Stripe già integrato nel backend;
- CLI per creare moduli in pochi secondi;
- Infrastruttura Docker già pronta (Traefik + Redis + DB).

**Obiettivo**: ridurre drasticamente il tempo per passare da idea a SaaS funzionante.


****

### Quando usarlo

**Perfetto per**:
•	SaaS B2B;
•	Gestionali;
•	Piattaforme multi-tenant;
•	MVP già pensati per crescere.

**Meno adatto per**:
•	App ultra client-side;
•	Editor visuali molto complessi;
•	Prodotti frontend-first tipo Figma/Trello-like.

****

### Licenza MIT

Sviluppatore: ``Quagliara Alessio``

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
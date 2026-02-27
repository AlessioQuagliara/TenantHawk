# SaaS Template – FastAPI + Next.js + Traefik

Template open source per SaaS multi-tenant:
- Backend: FastAPI async + SQLAlchemy 2 + asyncpg
- Frontend: Next.js 16 (App Router) + Tailwind
- Infra: Docker Compose + Traefik + Postgres

## Caratteristiche

- Routing admin multi-tenant via path: `/{tenant}/admin/...`
- Admin HTML (Jinja2) + landing marketing in Next.js
- DB Postgres, async engine, connection pooling
- Reverse proxy Traefik pronto per HTTPS (Let’s Encrypt) in prod

## Struttura

- `backend/`: FastAPI, Jinja admin, DB
- `frontend/`: Next.js landing
- `compose.yaml`: stack completo (Traefik, Postgres, backend, frontend)

## Avvio locale

```bash
docker compose up --build
```

Admin: http://admin.localhost

Landing: http://www.localhost

## License
MIT
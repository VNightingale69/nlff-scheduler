# Northern Lakes Flag Football Scheduler

Northern Lakes Flag Football (NLFF) scheduling MVP with a FastAPI backend, Next.js frontend, and PostgreSQL database.

## Tech Stack

- **Frontend:** Next.js (TypeScript) + Tailwind CSS
- **Backend:** FastAPI (Python)
- **Database:** PostgreSQL
- **ORM:** SQLAlchemy
- **Migrations:** Alembic
- **Container orchestration:** Docker Compose

## Project Structure

- `frontend/` - Next.js admin and public schedule UI
- `backend/` - FastAPI API, auth, migrations, and tests
- `docs/MVP_VERIFICATION.md` - MVP verification checklist + tester runbook
- `docker-compose.yml` - local multi-service environment

## Local Development Runbook (MVP)

### 1) Required environment variables

Backend environment variables:

- `DATABASE_URL` (default: `postgresql+psycopg://nlff:nlff_password@db:5432/nlff`)
- `JWT_SECRET_KEY` (default: `change-me-in-production`)
- `ACCESS_TOKEN_EXPIRE_MINUTES` (default: `30`)
- `REFRESH_TOKEN_EXPIRE_MINUTES` (default: `10080`)
- `ADMIN_SEED_EMAIL` (default: `admin@example.com`)
- `ADMIN_SEED_PASSWORD` (default: `ChangeMe123!`)
- `ADMIN_SEED_FULL_NAME` (default: `League Admin`)
- `CORS_ORIGINS` (default: `http://localhost:3000`; comma-separated list)

Frontend environment variables:

- `NEXT_PUBLIC_API_URL` (default in code: `http://localhost:8000`; `/api` is appended automatically if omitted)

> In Docker Compose, only `DATABASE_URL` is currently set explicitly. The remaining values use backend defaults unless you override them.

---

### 2) Start database, backend, and frontend (Docker)

From repo root:

```bash
docker compose up --build
```

Services:

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000/api
- Backend health: http://localhost:8000/health
- Public schedule page: http://localhost:3000/schedule

> Backend container startup now runs `alembic upgrade head` automatically before starting Uvicorn.

---

### 3) Run migrations

If services are already up (manual run still supported):

```bash
docker compose run --rm backend alembic upgrade head
```

Or as a one-off:

```bash
docker compose run --rm backend alembic upgrade head
```

---

### 4) Seed data

Current seed behavior:

- On backend startup, roles are seeded first (`league_admin`, `community_scheduler`) when missing.
- On backend startup, an admin user is created from `ADMIN_SEED_*` values when missing.
- Startup logs clearly indicate whether roles/admin were created or already existed.
- Initial divisions are inserted by the initial Alembic migration.

No separate seed CLI exists today; run migrations first, then start backend so startup seeding can run against existing tables.

---

### 5) Default admin login credentials

If defaults are unchanged:

- Email: `admin@example.com`
- Password: `ChangeMe123!`

Login page: http://localhost:3000/login

---

### 6) Run backend tests

From repo root:

```bash
docker compose exec backend python -m unittest backend/tests/test_scheduling_validation.py
```

This test suite validates conflict rules and confirms public schedule only includes published games.

---

### 7) Run frontend checks

From repo root:

```bash
docker compose exec frontend npm run lint
```

---

### 8) Manual MVP verification

Use the full step-by-step checklist in:

- [`docs/MVP_VERIFICATION.md`](docs/MVP_VERIFICATION.md)

That guide covers:

- Admin login
- Create organization
- Create host location
- Create field
- Create team
- Create hosting availability
- Create draft game
- Publish game
- Confirm public schedule shows published game
- Confirm public schedule does not show draft game
- Confirm conflict validation blocks invalid games

## Authentication & Authorization

Backend API supports JWT auth with role-based access control.

### Roles

- `league_admin`: Full access across all organizations.
- `community_scheduler`: Access restricted to assigned organization scope.

### Password rules

Passwords must be 8-128 chars and include:

- uppercase letter
- lowercase letter
- number
- special character

### Auth endpoints

- `POST /api/auth/login` → access + refresh tokens
- `POST /api/auth/refresh` → rotated access + refresh tokens
- `GET /api/auth/me` → current authenticated user

### CORS (local frontend ↔ backend)

- Backend uses FastAPI `CORSMiddleware`.
- Default allowed origin is `http://localhost:3000` (configurable via `CORS_ORIGINS`).
- Allowed methods: `GET, POST, PUT, PATCH, DELETE, OPTIONS`.
- Allowed headers: `*` (covers `Authorization`, `Content-Type`, and preflight-requested custom headers).
- Middleware is attached at the top-level FastAPI app, so it applies to all `/api/*` routes (including `/api/fields` and `/api/host-locations`) and error responses.



#### CORS preflight validation example

```bash
curl -i -X OPTIONS http://localhost:8000/api/fields \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type,authorization"
```

Expected response headers include:

- `access-control-allow-origin: http://localhost:3000`
- `access-control-allow-credentials: true`
- `access-control-allow-methods` containing `GET, POST, PUT, PATCH, DELETE, OPTIONS`

### Protected vs public routes

- Most `/api/*` endpoints require bearer access token.
- Public schedule endpoints are intentionally unauthenticated:
  - `/api/public/games`
  - `/api/public/schedule-filters`

## Current MVP Limitations

- Game management UI is raw-ID driven for related entities (UUID selection/entry), so setup order matters.
- Conflict validation is enforced for publishing games; draft games can still be saved with hard conflicts for planning.
- No automated schedule generation or playoff logic in this MVP.
- No dedicated seed script for full demo dataset; testers create most records manually.

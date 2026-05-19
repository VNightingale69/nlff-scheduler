# Northern Lakes Flag Football Scheduler

Initial project foundation for the Northern Lakes Flag Football scheduling system.

## Tech Stack

- **Frontend:** Next.js (TypeScript) + Tailwind CSS
- **Backend:** FastAPI (Python)
- **Database:** PostgreSQL
- **ORM:** SQLAlchemy
- **Migrations:** Alembic
- **Container orchestration:** Docker Compose

## Project Structure

- `frontend/` - Next.js + TypeScript + Tailwind base app
- `backend/` - FastAPI base app with SQLAlchemy and Alembic setup
- `docker-compose.yml` - local multi-service environment

## Quick Start

```bash
docker compose up --build
```

Services:

- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- Backend health endpoint: http://localhost:8000/health

## Notes

This repository currently contains only the foundation setup. It intentionally does **not** include:

- scheduling logic
- playoff logic
- automated schedule generation

## Authentication & Authorization

Backend API now supports JWT-based auth with role-based access control.

### Roles
- `league_admin`: Full access across all organizations.
- `community_scheduler`: Access restricted to their assigned organization.

### Environment Variables
Set these for secure deployments:
- `JWT_SECRET_KEY`
- `ACCESS_TOKEN_EXPIRE_MINUTES` (default: `30`)
- `REFRESH_TOKEN_EXPIRE_MINUTES` (default: `10080`)
- `ADMIN_SEED_EMAIL`
- `ADMIN_SEED_PASSWORD`
- `ADMIN_SEED_FULL_NAME`

### Password Rules
Passwords must be 8-128 chars and include:
- uppercase letter
- lowercase letter
- number
- special character

### Auth Endpoints
- `POST /api/auth/login` → returns access + refresh token
- `POST /api/auth/refresh` → returns rotated access + refresh token

### Protected Routes
Most `/api/*` routes require a valid bearer access token. Public schedule endpoints are intentionally unauthenticated: `/api/public/games` and `/api/public/schedule-filters`.
User creation is admin-only (`POST /api/users`).

### Organization Scope
- League Admin users can access all organizations and all organization-scoped entities.
- Community Scheduler users are restricted to records tied to their own `organization_id`.

### Seeding
On backend startup:
- roles are seeded (`league_admin`, `community_scheduler`)
- admin user is seeded using `ADMIN_SEED_*` env vars

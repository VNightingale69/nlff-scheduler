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

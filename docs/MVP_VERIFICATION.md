# MVP Verification Checklist and Developer Runbook

This document is the practical test guide for validating the Northern Lakes Flag Football scheduling MVP.

## 1) Local runbook

### Prerequisites

- Docker + Docker Compose installed

### Start stack

From repo root:

```bash
docker compose up --build
```

Expected local URLs:

- Frontend admin + public UI: http://localhost:3000
- Backend API root path: http://localhost:8000/api
- Backend health: http://localhost:8000/health
- Public schedule page: http://localhost:3000/schedule

### Required environment variables

Backend:

- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `REFRESH_TOKEN_EXPIRE_MINUTES`
- `ADMIN_SEED_EMAIL`
- `ADMIN_SEED_PASSWORD`
- `ADMIN_SEED_FULL_NAME`

Frontend:

- `NEXT_PUBLIC_API_URL`

> Defaults exist in code for all values above. `NEXT_PUBLIC_API_URL` can be either `http://localhost:8000` or `http://localhost:8000/api`.

### Migrations

```bash
docker compose run --rm backend alembic upgrade head
```

### Seeding

Seeding is currently automatic and split across startup + migrations:

- Migration seeds baseline divisions.
- Backend startup seeds roles/admin only after required tables exist.
- Backend startup seeds admin user from `ADMIN_SEED_*` values when missing.

### Default admin login (if env defaults are used)

- Email: `admin@example.com`
- Password: `ChangeMe123!`
- Login page: http://localhost:3000/login

### Backend tests

```bash
docker compose exec backend python -m unittest backend/tests/test_scheduling_validation.py
```

### Frontend checks

```bash
docker compose exec frontend npm run lint
```

---

## 2) Known MVP limitations

- Admin UI is intentionally simple and requires selecting/working with existing related records (UUID-backed).
- No one-click sample dataset loader exists; manual setup is expected for MVP verification.
- Conflict validation blocks publishing invalid games, but allows draft saves for scheduling work-in-progress.
- No automated schedule generation in this phase.
- Public schedule only displays games with status code `published`.

---

## 3) MVP verification checklist

Use this section as a test script. Record pass/fail for each step.

## 0. Pre-check

- [ ] Services are running via Docker Compose.
- [ ] `/health` returns `{"status": "ok"}`.
- [ ] Admin login credentials are known.

## 1. Admin login

- [ ] Navigate to `http://localhost:3000/login`.
- [ ] Sign in with admin credentials.
- [ ] Confirm dashboard loads and organization management is available.

## 2. Create organization

- [ ] Go to **Dashboard → Organizations**.
- [ ] Create organization (example name: `Northern Lakes - Community A`).
- [ ] Confirm it appears in the organizations table.

## 3. Create host location

- [ ] Go to **Dashboard → Host Locations**.
- [ ] Create host location tied to the organization from step 2.
- [ ] Confirm location appears in the table.

## 4. Create field

Use a layout type compatible with your test division:
- [ ] Small: Coed K-1, Coed 2-3, Girls K-2, Girls 3-5
- [ ] Large: Coed 4-5, Coed 6-7, Coed 8, Girls 6-8
- [ ] Both: field supports either layout

## 5. Create team

- [ ] Go to **Dashboard → Teams**.
- [ ] Create Team A and Team B under the same division + organization.
- [ ] Confirm both teams appear in the table.

## 6. Create hosting availability

- [ ] Go to **Dashboard → Hosting Availability**.
- [ ] Add an availability window for the field/date you will use for games.
- [ ] Confirm row appears in the table.

## 7. Create draft game

- [ ] Go to **Dashboard → Games**.
- [ ] Create a game using:
  - season
  - week
  - division
  - home team
  - away team
  - field
  - `draft` game status
  - valid date/time
- [ ] Confirm game is saved with `draft` status.

## 8. Publish game

- [ ] Edit the draft game and change status to `published`.
- [ ] Save changes.
- [ ] Confirm status now appears as `published` in games list.

## 9. Confirm public schedule shows published game

- [ ] Open `http://localhost:3000/schedule`.
- [ ] Apply filters if needed.
- [ ] Confirm published game is visible in public schedule results.

## 10. Confirm public schedule does not show draft game

- [ ] Create a second game with identical setup but keep status as `draft`.
- [ ] Re-open or refresh public schedule page.
- [ ] Confirm draft game is **not** listed.

## 11. Confirm conflict validation blocks invalid published games

Suggested validation scenario (team overlap):

- [ ] Keep an existing published game for Team A at a given time.
- [ ] Attempt to create a second game at overlapping time with Team A again.
- [ ] Set new game status to `published`.
- [ ] Confirm save is blocked with hard conflict validation feedback.

Control check:

- [ ] Repeat same conflicting payload but set status to `draft`.
- [ ] Confirm draft save is allowed, and validation shows hard conflict information.

---

## 4) Suggested evidence capture for MVP signoff

For each checklist item, capture one of:

- Screenshot of UI state, or
- API response payload, or
- short note with timestamp and tester initials.

Minimum recommended artifacts:

- Login success screenshot
- Created organization + host location + field + teams rows
- Game row showing `published`
- Public schedule row showing published game
- Public schedule view proving draft exclusion
- Conflict validation error output for invalid publish attempt

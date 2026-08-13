# Schedule permission flow

## Before Schedule Review

* Public schedule reads use `GET /api/public/schedule` and only return games in weeks whose authoritative `Week.publication_status` is `PUBLISHED`.
* League and Scheduling Administrators are the only schedule-management roles. `require_schedule_admin` protects game creation, updates, deletion, movement, import, regeneration, repair, validation, and administrative export. `require_schedule_publisher` separately protects publication and unpublication, and resolves to the same two roles.
* Community Administrators are authenticated and organization-scoped for the community data they can manage. They cannot pass either schedule mutation dependency and did not previously have an authenticated draft schedule reader.
* Frontend navigation sends League and Scheduling Administrators to the builder, readiness, management, publication, and import tools. Community Administrators only receive their community-management links and the public published-schedule link.

## Schedule Review capability

`GET /api/schedule-review` and `GET /api/schedule-review/export.csv` accept League, Scheduling, and Community Administrators. They read persisted final `Game` rows, omit administrative metadata and record identifiers from games, and return the backend-derived week publication state (`PUBLISHED`, `DRAFT`, or `PUBLISHED_CHANGES_PENDING`).

For a Community Administrator, the default `my_organization` scope is derived from the authenticated user's organization; no browser-provided organization identifier establishes that scope. The explicit `league` scope provides league-wide context without changing authorization. The review API has no mutation method, while every existing schedule mutation remains protected by the existing schedule-admin or publisher dependency.

The dedicated `/admin/schedule-review` page is intentionally read-only. It provides filters, alternate grouping and hosting views, printing, and a safe CSV export, but has no schedule-management callbacks or controls. Public endpoint behavior is unchanged.

# Publish a bracket without its schedule

In Tournament Builder, select Bracket View and choose Publish Bracket Only.
Open Public Bracket provides a link with tournament selection and division links.
Bracket edits and official published scores appear automatically; Update Published
Bracket also reaffirms publication. Unpublish Bracket removes bracket-only access.
Existing full tournament publication and administrator scheduling are independent.
If full tournament publication remains enabled, its existing public view stays available.

The dedicated public endpoint is GET /api/public/tournaments/{id}/bracket-only
and accepts division_id. It uses an explicit game-field allowlist, excluding game
dates, times, host IDs/names, field IDs/names, and administrator review state.
Unpublished scores remain hidden. The HTML and SVG/PNG/PDF exports omit scheduling
labels when the API omits those fields. Single and double elimination use the
existing shared renderer and feeder graph.

Deployment requires running `alembic upgrade head` from backend before starting
the updated API. Migration 20261013_0084 adds bracket_is_published with a false
default and preserves existing tournament and schedule publication.

## Combined season view

The public tournament selector groups published tournament records belonging to
the same season. For the 2026 single- and double-elimination tournaments, the
combined option is 2026 Tournament View. Both sets of division brackets appear
on the same page, with their existing feeder graphs, results and per-division
exports. Existing tournament links resolve to their combined season view. Only
published records are included; bracket-only links retain the scheduling-free
API and rendering behavior. Different seasons remain separate.

## Tournament games on the public schedule

Use Publish Tournament in Tournament Builder to expose assigned game dates, times,
locations and fields on the public Schedule page. Publishing only the bracket
never exposes these assignments. The week selector includes a combined season
tournament option with its date range, covering both elimination formats.
All Weeks includes regular and fully published tournament schedules; selecting
a regular week excludes tournament games. List View, Hosting View, filters and
Print / PDF use the same saved assignments. Unresolved teams display Winner/Loser
of Game references. Undated games are omitted until dates and times are assigned.

GET /api/public/tournament-schedule provides schedule rows and filter options.
It accepts season_id, host_location_id, organization_id, division_id and team_id.
No schema migration is required for this addition.

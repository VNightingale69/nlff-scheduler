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

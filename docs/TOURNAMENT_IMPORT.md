# Tournament schedule import

Create a tournament with a default single- or double-elimination format. After loading seeds, each division can select its own format. Double elimination advances both winners and losers and uses one grand final without a championship reset. Existing tournaments keep their single-elimination format. An unscored division can change format using **Format for regeneration** and **Regenerate Bracket**; this replaces its game IDs and assignments while retaining saved seeds and exclusions. Divisions with recorded results cannot be regenerated.

Use **Import Tournament Schedule** inside the selected Tournament Builder card. The separate **Import Schedule** page continues to handle season schedules.

CSV headers: `Date, Time, Division, Game ID, Round, Host Location, Field, Home Team, Away Team`. Optional `Home Seed` and `Away Seed` are checked when supplied. CSV game IDs must be unique within their division. `Winner of K1` and `Loser of D45-3` refer to CSV IDs within the same division. Matching uses actual team names, round, and feeder outcomes; CSV numbers are never assumed to equal the application's game numbers. Fields must match active canonical fields at the named host location. Six/seven-team single-elimination brackets accept Quarterfinal as an alias for the generated Play-In round.

1. Select the CSV. For a file containing conditional reset games, explicitly select **Exclude conditional/reset games** to follow the no-reset rule.
2. Select **Validate and Preview**. Review matched bracket game numbers, round labels, assignments, errors, and excluded rows. Preview makes no schedule changes.
3. Resolve every error. A missing division, different seed order, or unsupported bracket requires correcting the tournament or CSV. The importer does not generate missing divisions, create games, or replace seeds.
4. Confirm replacement and select **Apply Tournament Schedule**. The entire validated set applies in one transaction. File or bracket changes since preview require a new preview. Publication, scores, and regular-season records are preserved. Applying to a published tournament updates its public schedule.

For the TOSC file, use single elimination for COED K-1, COED 2-3, GIRLS 3-5, and GIRLS 6-8; double elimination for COED 4-5 and COED 6-7. Include all six divisions and set seeds to match the CSV. Excluding its two Championship Reset rows leaves 42 assignments.

Validation detects duplicate game matches, ambiguous sites/fields, invalid dates/times, field conflicts at identical kickoff times, and feeders starting at or after their dependent game. It does not prove that a full game's duration fits between assignments or check regular-season facility availability. Half-end/game-end timing and notes in the CSV are not persisted by the tournament model.

API: `POST /api/tournaments/{id}/schedule-import` accepts a multipart `file` and optional `skip_resets=true`; preview returns a fingerprint. Apply the same upload with `apply=true&fingerprint=...` and the same exclusion option. Only league and scheduling administrators may use this endpoint. Migration `20261013_0083` adds per-division format and winner/loser source outcomes, with defaults that preserve existing single-elimination records.

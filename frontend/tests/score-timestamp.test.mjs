import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

import { formatDateTime, formatDateTimeParts } from '../src/lib/displayFormat.ts';

const summerTimestamp = '2026-08-16T15:08:53.695907+00:00';
const winterTimestamp = '2026-01-16T15:08:53.695907+00:00';

test('score_entry_formats_submitted_at and score_entry_formats_last_updated', () => {
  const source = fs.readFileSync(new URL('../src/app/(dashboard)/admin/score-entry/page.tsx', import.meta.url), 'utf8');
  assert.match(source, /'Submitted'.*'Updated'/);
  assert.match(source, /<ScoreTimestamp value=\{g\.submitted_at\} \/>/);
  assert.match(source, /<ScoreTimestamp value=\{g\.last_updated_at \|\| g\.submitted_at\} \/>/);
  assert.doesNotMatch(source, /Submitted At|Last Updated/);
});

test('score_timestamp_converts_utc_to_chicago_timezone', () => {
  assert.deepEqual(formatDateTimeParts(summerTimestamp), {
    dateText: 'Aug 16, 2026',
    timeText: '10:08 AM',
  });
});

test('score_timestamp_handles_daylight_saving_time', () => {
  assert.equal(formatDateTime(summerTimestamp), 'Aug 16, 2026 10:08 AM'); // CDT (UTC-5)
  assert.equal(formatDateTime(winterTimestamp), 'Jan 16, 2026 9:08 AM'); // CST (UTC-6)
});

test('score_timestamp_omits_seconds_and_milliseconds', () => {
  const visible = formatDateTime(summerTimestamp);
  for (const backendDetail of ['T', '+00:00', '.695907', ':53']) {
    assert.equal(visible.includes(backendDetail), false);
  }
});

test('score_timestamp_null_displays_dash', () => {
  assert.equal(formatDateTime(null), '—');
  assert.equal(formatDateTime(undefined), '—');
  assert.equal(formatDateTime(''), '—');
  assert.equal(formatDateTime('not-a-date'), '—');
});

test('score_timestamp_sorting_uses_original_value', () => {
  const rows = [{ submitted_at: summerTimestamp }, { submitted_at: winterTimestamp }];
  rows.sort((a, b) => new Date(a.submitted_at).getTime() - new Date(b.submitted_at).getTime());
  assert.deepEqual(rows.map((row) => row.submitted_at), [winterTimestamp, summerTimestamp]);

  const component = fs.readFileSync(new URL('../src/components/ScoreTimestamp.tsx', import.meta.url), 'utf8');
  assert.match(component, /title=\{value \|\| undefined\}/);
});

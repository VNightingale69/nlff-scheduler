import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const page = readFileSync(new URL('../src/app/(dashboard)/admin/manual-schedule-builder/page.tsx', import.meta.url), 'utf8');

assert.match(page, /\(options\.fields \|\| \[\]\)/, 'uses canonical fields returned by the API');
assert.match(page, /String\(field\.host_location_id \|\| ''\) === selectedHostId && field\.is_active/, 'filters active fields by selected host location');
assert.match(page, /field\.display_name \|\| field\.name/, 'renders the canonical short display name');
assert.match(page, /value=\{pendingEdit\.field_id \|\| ''\}/, 'select value is the persisted canonical field ID');
assert.match(page, /value=\{field\.field_id \|\| field\.id\}/, 'option values are canonical field IDs');
assert.match(page, /host_location_id: e\.target\.value, field_id: '', field_instance_id: ''/, 'changing host clears an invalid field immediately');
assert.match(page, /pendingEdit\?\.field_id && !values\.some/, 'the current persisted assignment remains represented');
assert.match(page, /isMissingFieldAssignment\(pendingEdit\)/, 'missing-field state uses the effective editable assignment');
assert.match(page, />Unsaved<\/span>/, 'a selected dirty field is shown as unsaved rather than missing');
assert.doesNotMatch(page, /required_field_type[^\n]+\.filter/, 'field type compatibility does not remove physical fields');
assert.match(page, /setPendingGameEdits\(Object\.fromEntries\(games\.map/, 'global edit mode initializes every existing row immediately');

console.log('manual schedule canonical field option checks passed');

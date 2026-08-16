import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const page = readFileSync(new URL('../src/app/(dashboard)/admin/manual-schedule-builder/page.tsx', import.meta.url), 'utf8');

assert.match(page, /\(options\.fields \|\| \[\]\)/, 'uses canonical fields returned by the API');
assert.match(page, /String\(field\.host_location_id \|\| ''\) === selectedHostId && field\.is_active/, 'filters active fields by selected host location ID');
assert.match(page, /String\(field\.field_type \|\| ''\)\.toUpperCase\(\) === requiredFieldType/, 'filters options by the division-compatible physical field type');
assert.match(page, /field\.display_name \|\| field\.name/, 'renders the canonical short display name');
assert.match(page, /value=\{pendingEdit\.field_id \|\| ''\}/, 'select value is the persisted canonical field ID');
assert.match(page, /value=\{field\.field_id \|\| field\.id\}/, 'option values are canonical field IDs');
assert.match(page, /host_location_id: e\.target\.value, field_id: '', field_instance_id: ''/, 'changing host clears an invalid field immediately');
assert.match(page, /pendingEdit\?\.field_id && !values\.some/, 'the current persisted assignment remains represented');
assert.match(page, /isMissingFieldAssignment\(pendingEdit\)/, 'missing-field state uses the effective editable assignment');
assert.match(page, />Unsaved<\/span>/, 'a selected dirty field is shown as unsaved rather than missing');
assert.match(page, /updatePendingEditForGame\(g, \{ field_id: e\.target\.value, field_instance_id:/, 'selecting Field 1 or Field 3 stores its canonical ID in the dirty row');
assert.match(page, /game_id: pendingEdit\.id,[\s\S]*field_id: pendingEdit\.field_id,/, 'bulk payload sends each dirty game ID and canonical field ID');
assert.match(page, /field_instance_id: normalizeOptionalUuid\(pendingEdit\.field_instance_id\)/, 'an empty optional field-instance UUID is normalized before serialization');
assert.match(page, /apiFetch\('\/schedule-management\/games\/manual-edit\/bulk'/, 'Save Changes invokes the bulk API');
assert.match(page, /type='button'[\s\S]*disabled=\{!hasPendingBulkEdits \|\| bulkSaveLoading\}/, 'Save Changes is a non-submit button and valid dirty rows are not silently blocked by advisory state');
assert.doesNotMatch(page, /if \(hasInvalidPendingEdits\)[^{]*\{[^}]*return/, 'client-side advisory state cannot prevent the bulk API attempt');
assert.match(page, /buildBulkPayload\(editsToSave, saveWithWarningOverride\)/, 'the request is built from the exact dirty-row snapshot captured by the click handler');
assert.match(page, /while \(true\)[\s\S]*saveWithWarningOverride = true/, 'warning confirmation retries the request inside the active save invocation');
assert.doesNotMatch(page, /await saveBulkInlineEdits\(true\)/, 'warning retry cannot be discarded by recursively hitting the loading guard');
assert.match(page, /Object\.entries\(editableGameSnapshot\(edit\)\)/, 'success verifies every editable canonical value, including fields and notes, returned by the server');
assert.match(page, /Unable to save schedule changes\. \$\{edits\.length\}/, 'bulk failures remain visible with affected-game context and the backend reason');
assert.doesNotMatch(page, /setIsBulkEditMode\(false\);\s*await load/, 'successful saves leave global edit mode active');
assert.match(page, /No active \$\{divisionDefaultFieldType \|\| 'compatible'\} fields are available at/, 'explains when a host has fields but none match the division type');
assert.match(page, /No active fields configured for \$\{selectedHost\?\.name/, 'explains when the selected host has no active fields');
assert.match(page, /setPendingGameEdits\(Object\.fromEntries\(games\.map/, 'global edit mode initializes every existing row immediately');

console.log('manual schedule canonical field option checks passed');

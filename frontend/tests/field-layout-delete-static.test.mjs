import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/components/FieldAreaManager.tsx', import.meta.url), 'utf8');

assert.match(source, /canDeleteFieldDefinitions && <button[^>]+onClick=\{\(\) => setLayoutDeleteTarget\(config\)\}>Delete Layout<\/button>/);
assert.match(source, /<h2 id='delete-layout-title'[^>]*>Delete field layout\?<\/h2>/);
assert.match(source, /This permanently removes this field configuration from the host location\./);
assert.match(source, /await apiFetch\(`\/host-location-configurations\/\$\{layoutDeleteTarget\.id\}`[^\n]+method: 'DELETE'/);
assert.match(source, /setMessage\('Field layout deleted successfully\.'\)/);
assert.match(source, /bg-rose-700[^>]+onClick=\{confirmLayoutDeletion\}/);

console.log('field layout delete static checks passed');

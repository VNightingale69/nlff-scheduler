import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/components/FieldAreaManager.tsx', import.meta.url), 'utf8');

assert.match(source, /Show inactive \/ legacy layouts/);
assert.match(source, /host-location-configurations\/\$\{config\.id\}\/active/);
assert.match(source, /config\.is_active \? 'Deactivate' : 'Activate'/);
assert.match(source, /showInactiveLayouts \|\| config\.is_active/);
assert.match(source, /Active — Configuration Error: No fields assigned/);
assert.match(source, /⚠ No physical fields assigned/);

console.log('field layout status static checks passed');

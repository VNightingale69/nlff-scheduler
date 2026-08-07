import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/components/HostingAvailabilityManager.tsx', import.meta.url), 'utf8');

assert.match(source, /Available Layout Mode: Auto-select/);
assert.match(source, /Layout: Auto-select/);
assert.match(source, /Capacity: Will be determined during slot generation/);
assert.match(source, /Current Generated Layout:.*Not generated/);
assert.match(source, /Generated Capacity:/);

console.log('hosting availability auto-layout static checks passed');

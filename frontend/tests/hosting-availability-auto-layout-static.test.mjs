import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/components/HostingAvailabilityManager.tsx', import.meta.url), 'utf8');

assert.match(source, /Available Layout Mode: Auto-select/);
assert.match(source, /Layout: Auto-select/);
assert.match(source, /Capacity: Will be determined during slot generation/);
assert.match(source, /Current Generated Layout:.*Not generated/);
assert.match(source, /Generated Capacity:/);
assert.match(source, /generated_slots_by_size\?\.SMALL/);
assert.match(source, /requirements\.projectedSmallGames \* smallFieldSlots \/ dateTotals\.small/);
assert.doesNotMatch(source, /const projectedGames = requirements\.projectedSmallGames \+ requirements\.projectedLargeGames/);
assert.match(source, /Capacity diagnostics/);
assert.match(source, /Exclusion reason:/);

console.log('hosting availability auto-layout static checks passed');

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/components/HostingAvailabilityManager.tsx', import.meta.url), 'utf8');

assert.match(source, /Layout mode:.*Auto-select layout.*Manually selected layout/);
assert.match(source, /Capacity: Auto-selected during slot generation/);
assert.match(source, /entry\.auto_select_turf_layout && !entry\.layout_resolved/);
assert.match(source, /entry\.layout_resolved \? 'Selected Layout' : 'Available Layout'/);

console.log('hosting availability auto-layout static checks passed');

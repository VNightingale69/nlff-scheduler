import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/components/HostAvailabilityMatrix.tsx', import.meta.url), 'utf8');

assert.match(source, /Mark Hosting TBD/);
assert.match(source, /Resolve TBD Hosting/);
assert.match(source, /TBD \/ Deferred/);
assert.match(source, /Not required — placement deferred/);
assert.match(source, /Field capacity:<\/b> Deferred until host assignment/);
assert.match(source, /host-availability-matrix\/hosting-status/);

console.log('host availability deferred state static checks passed');

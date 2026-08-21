import assert from 'node:assert/strict';
import fs from 'node:fs';

const read = path => fs.readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');
const page = read('app/locations/page.tsx');
const schedule = read('app/schedule/page.tsx');
const admin = read('app/(dashboard)/admin/host-locations/page.tsx');

assert.match(page, /public\/hosting-locations/);
assert.match(page, /Address not yet available/);
assert.match(page, /complete && <a/);
assert.match(page, /encodeURIComponent\(addressQuery\(location\)\)/);
assert.match(page, /aria-label=\{`Get directions to \$\{location\.name\}`\}/);
assert.match(page, /grid-cols-1/);
assert.match(page, /min-h-11/);
assert.match(schedule, /href=\{`\/locations#location-\$\{g\.host_location_id\}`\}/);
assert.match(admin, /Public Location Notes/);
console.log('public locations static checks passed');

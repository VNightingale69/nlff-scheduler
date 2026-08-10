import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../src/components/HostingAvailabilityManager.tsx', import.meta.url), 'utf8');
const auth = fs.readFileSync(new URL('../src/lib/auth.ts', import.meta.url), 'utf8');

assert.match(source, /VIEW ONLY —/);
assert.match(source, /My Community/);
assert.match(source, /View Only/);
assert.match(source, /canEditCommunity \? <div className='flex gap-2'>/);
assert.ok(source.includes("{canEditCommunity ? <button className='rounded bg-emerald-700"));
assert.match(source, /disabled=\{!canEditCommunity\}/);
assert.match(auth, /function canManageCommunityHosting/);
console.log('hosting availability league view static checks passed');

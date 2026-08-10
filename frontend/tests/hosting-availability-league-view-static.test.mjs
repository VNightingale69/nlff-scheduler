import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../src/components/HostingAvailabilityManager.tsx', import.meta.url), 'utf8');
const matrix = fs.readFileSync(new URL('../src/components/CommunityHostAvailabilityMatrix.tsx', import.meta.url), 'utf8');
const page = fs.readFileSync(new URL('../src/app/(dashboard)/dashboard/hosting-availability/page.tsx', import.meta.url), 'utf8');
const auth = fs.readFileSync(new URL('../src/lib/auth.ts', import.meta.url), 'utf8');

assert.match(source, /VIEW ONLY —/);
assert.match(source, /My Community/);
assert.match(source, /View Only/);
assert.match(source, /canEditCommunity \? <div className='flex gap-2'>/);
assert.ok(source.includes("{canEditCommunity ? <button className='rounded bg-emerald-700"));
assert.match(source, /disabled=\{!canEditCommunity\}/);
assert.match(auth, /function canManageCommunityHosting/);
assert.match(page, /CommunityHostAvailabilityMatrix/);
assert.doesNotMatch(page, /HostingAvailabilityManager/);
assert.match(matrix, /All Communities/);
assert.match(matrix, /My Community/);
assert.match(matrix, /VIEW ONLY/);
assert.match(matrix, /League blackout/);
assert.match(matrix, /canManageCommunityHosting\(user, row\.community_id\)/);
assert.doesNotMatch(matrix, /Generate Suggested Host Plan|Run Auto-Schedule|Lock Selected Week/);
console.log('hosting availability league view static checks passed');

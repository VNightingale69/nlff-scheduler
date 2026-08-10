import assert from 'node:assert/strict';
import fs from 'node:fs';

const matrix = fs.readFileSync(new URL('../src/components/HostAvailabilityMatrix.tsx', import.meta.url), 'utf8');
const page = fs.readFileSync(new URL('../src/app/(dashboard)/dashboard/hosting-availability/page.tsx', import.meta.url), 'utf8');

assert.match(page, /HostAvailabilityMatrix mode="community-readonly"/);
assert.match(matrix, /type HostAvailabilityMatrixMode = 'scheduler' \| 'community-readonly'/);
assert.match(matrix, /const isReadOnly = mode === 'community-readonly'/);
assert.match(matrix, /League-wide hosting plan — Read Only/);
assert.match(matrix, /isReadOnly \? <span[\s\S]*cursor-default[\s\S]*: <button[\s\S]*onClick=\{\(event\) => handleCellClick/);
assert.match(matrix, /\{!isReadOnly \? <div className='mt-4 flex flex-wrap gap-2'>/);
assert.match(matrix, /\{!isReadOnly \? <aside/);
assert.match(matrix, /Weekly filter/);
assert.match(matrix, /Filter by community/);
assert.match(matrix, /Filter by location/);
assert.match(matrix, /Clear Filters/);
assert.match(matrix, /locked hosting site/);
assert.match(matrix, /hosting plan not yet finalized/);
assert.doesNotMatch(page, /Select Organization|Select Hosting Site|HostingAvailabilityManager/);

assert.match(matrix, /Generate Suggested Host Plan/);
assert.match(matrix, /Save Matrix Changes/);
assert.match(matrix, /onContextMenu=\{\(event\) => handleCellMenu/);
assert.match(matrix, /summaries/);
console.log('hosting availability league view static checks passed');

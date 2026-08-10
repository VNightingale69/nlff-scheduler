import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/components/HostingAvailabilityManager.tsx', import.meta.url), 'utf8');

// Community administrators always enter with empty organization/site selections,
// even when a URL contains a prior selection or their account owns one community.
assert.match(source, /if \(user\?\.role_name === 'COMMUNITY_ADMIN'\) \{\s*setOrgId\(''\);\s*setHostId\(''\);/);
assert.match(source, /<option value=''>Select organization<\/option>/);
assert.match(source, /<option value=''>Select hosting site<\/option>/);
assert.match(source, /Select an organization to view hosting availability\./);
assert.match(source, /disabled=\{isCommunityAdmin && !effectiveOrgId\}/);

// Changing communities clears every dependent hosting selection.
assert.match(source, /const selectOrganization = \(nextOrgId: string\) => \{[\s\S]*setHostId\(''\);[\s\S]*setSelectedWeekIds\(\[\]\);[\s\S]*setSavedAvailability\(\[\]\);/);
assert.match(source, /onChange=\{\(e\) => selectOrganization\(e\.target\.value\)\}/);

// Scheduler diagnostics remain in the shared table, but are conditionally omitted
// from both headers and cells for community administrators.
assert.match(source, /const showSchedulerDiagnostics = canManageSchedule\(user\);/);
assert.match(source, /showSchedulerDiagnostics \? <>\s*<th className='p-2'>Readiness<\/th><th className='p-2'>Validation indicators<\/th>/);
assert.match(source, /showSchedulerDiagnostics \? <>\s*<td className='p-2'><span title=\{READINESS_DEFINITIONS\[row\.readiness\]\}/);

console.log('hosting availability community view static checks passed');

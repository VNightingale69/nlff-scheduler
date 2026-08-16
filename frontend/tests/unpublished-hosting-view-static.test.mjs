import assert from 'node:assert/strict';
import fs from 'node:fs';

const management = fs.readFileSync(new URL('../src/app/(dashboard)/admin/schedule-management/page.tsx', import.meta.url), 'utf8');
const review = fs.readFileSync(new URL('../src/app/(dashboard)/admin/schedule-review/page.tsx', import.meta.url), 'utf8');
const hosting = fs.readFileSync(new URL('../src/components/schedule/HostingView.tsx', import.meta.url), 'utf8');
const css = fs.readFileSync(new URL('../src/app/globals.css', import.meta.url), 'utf8');

assert.match(management, /Schedule View/);
assert.match(management, /Hosting View/);
assert.match(management, /mode='unpublished'/);
assert.match(management, /Print Hosting View/);
assert.match(management, /schedule-management\/games/, 'preview must use saved administrative games');
assert.doesNotMatch(hosting, /fetch\(|apiFetch|drag/i, 'shared report must remain presentation-only');
assert.match(hosting, /Pre-published schedule/);
assert.match(hosting, /physicalArea/);
assert.match(hosting, /fieldLane/);
assert.match(hosting, /hostGames\.filter/, 'all simultaneous games in a lane must be retained');
assert.match(review, /HostingView mode='unpublished'/, 'community-visible review reuses the report');
assert.match(css, /@media \(max-width: 640px\)[\s\S]*hosting-mobile-list/);
assert.match(css, /hosting-game-cell[\s\S]*break-inside: avoid/);

console.log('unpublished hosting view static checks passed');

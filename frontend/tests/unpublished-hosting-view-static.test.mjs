import assert from 'node:assert/strict';
import fs from 'node:fs';

const management = fs.readFileSync(new URL('../src/app/(dashboard)/admin/schedule-management/page.tsx', import.meta.url), 'utf8');
const review = fs.readFileSync(new URL('../src/app/(dashboard)/admin/schedule-review/page.tsx', import.meta.url), 'utf8');
const hosting = fs.readFileSync(new URL('../src/components/schedule/HostingView.tsx', import.meta.url), 'utf8');
const css = fs.readFileSync(new URL('../src/app/globals.css', import.meta.url), 'utf8');

assert.match(management, /Schedule View/);
assert.match(management, /Hosting View/);
assert.match(management, /publicationStatus='DRAFT'/);
assert.match(management, /Print Hosting View/);
assert.match(management, /schedule-management\/games/, 'preview must use saved administrative games');
assert.doesNotMatch(hosting, /fetch\(|apiFetch|drag/i, 'shared report must remain presentation-only');
assert.match(hosting, /Pre-published schedule/);
assert.match(hosting, /physicalArea/);
assert.match(hosting, /fieldLane/);
assert.match(hosting, /cells\.get/, 'cells must be populated by canonical saved field identity');
assert.match(management, /physicalFieldId: game\.physical_field_id/);
assert.match(review, /physicalFieldId: game\.physical_field_id/);
assert.match(review, /publicationStatus=\{week\.publication_status/, 'hosting view consumes each week canonical backend state');
assert.doesNotMatch(review, /HostingView mode='unpublished'/, 'hosting view must not force every week into draft mode');
assert.match(hosting, /publicationStatus === 'DRAFT'/, 'only a draft week receives the pre-published warning');
assert.match(hosting, /publicationStatus === 'PUBLISHED_CHANGES_PENDING'/, 'pending state has a distinct banner');
assert.match(hosting, /Schedule changes pending/);
assert.match(hosting, /has been published, but the administrative schedule contains changes that have not yet been republished/);
assert.match(css, /@media \(max-width: 640px\)[\s\S]*hosting-mobile-list/);
assert.match(css, /hosting-game-cell[\s\S]*break-inside: avoid/);

console.log('unpublished hosting view static checks passed');

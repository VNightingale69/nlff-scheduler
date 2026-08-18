import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const config = readFileSync(new URL('../src/lib/divisionScoring.ts', import.meta.url), 'utf8');
const guide = readFileSync(new URL('../src/components/public/TouchdownGuide.tsx', import.meta.url), 'utf8');
const results = readFileSync(new URL('../src/components/public/PublicResults.tsx', import.meta.url), 'utf8');

const expected = {
  small: ['Coed K-1', 'Coed 2-3', 'Girls K-2'],
  medium: ['Coed 4-5', 'Girls 3-5'],
  large: ['Coed 6-7', 'Coed 8', 'Girls 6-8'],
};
for (const [fieldType, divisions] of Object.entries(expected)) {
  assert.match(config, new RegExp(`fieldType: '${fieldType}'`));
  for (const division of divisions) assert.ok(config.includes(division));
}
for (const obsolete of ['Girls K/1st', 'Girls 2nd/3rd', 'Girls 4th/5th', 'Girls 6th/7th/8th']) assert.ok(!(config + guide).includes(obsolete));

assert.match(guide, /No extra-point attempts/);
assert.match(guide, /Optional 1-point or 2-point conversion/);
assert.match(guide, /data-testid='desktop-touchdown-guide'/);
assert.match(guide, /data-testid='mobile-touchdown-guide'/);
assert.doesNotMatch(guide, /min-\[900px\]:sticky/);
assert.match(guide, /variant: 'desktop' \| 'mobile'/);
assert.match(guide, /<button type='button' aria-expanded=\{expanded\} aria-controls=\{contentId\}/);
assert.match(guide, /hidden=\{!expanded\}/);
assert.match(guide, /min-\[900px\]:hidden/);
assert.match(guide, /hidden rounded-xl.*min-\[900px\]:block/);
assert.doesNotMatch(guide, /<details/);
assert.match(results, /min-\[900px\]:grid-cols-\[minmax\(0,3fr\)_minmax\(250px,1fr\)\]/);
assert.match(results, /<TouchdownGuide variant='mobile' \/>.*Showing/s);
assert.match(results, /<TouchdownGuide variant='desktop' \/>/);
assert.match(results, /data-testid='scores-guide-sidebar'/);
assert.match(results, /scores-guide-sidebar' className='hidden/);
assert.match(results, /min-\[900px\]:sticky/);
assert.match(results, /min-\[900px\]:top-20/);
assert.match(results, /min-\[900px\]:self-start/);
assert.doesNotMatch(results, /(?:^|\s)sticky(?:\s|')/);

console.log('public scores touchdown guide tests passed');

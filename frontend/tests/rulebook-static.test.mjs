import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const admin = readFileSync(new URL('../src/app/(dashboard)/admin/rulebook/page.tsx', import.meta.url), 'utf8');
const publicPage = readFileSync(new URL('../src/app/rulebook/page.tsx', import.meta.url), 'utf8');
for (const source of [admin, publicPage]) {
  assert.match(source, /view_url: string/); assert.match(source, /download_url: string/);
  assert.match(source, /const rulebookUrl =/); assert.match(source, /path\.startsWith\('\/api\/'\) \? path\.slice\(4\) : path/);
  assert.doesNotMatch(source, /createObjectURL|blob:/);
}
assert.match(admin, /Official Rulebook/); assert.match(admin, /Rule Infographic/);
assert.match(admin, /\/admin\/rule-infographic\/upload/); assert.match(admin, /25 MB maximum file size/);
assert.match(admin, /No Rule Infographic has been uploaded/); assert.match(admin, /Upload\/Replace Rule Infographic PDF/);
assert.match(publicPage, /\/public\/rule-infographic/); assert.match(publicPage, /infographic&&<Resource/);
assert.match(publicPage, /Quick-reference guide for scoring and commonly used game rules/);
console.log('rulebook and infographic static checks passed');

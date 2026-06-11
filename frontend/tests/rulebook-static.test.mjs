import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const adminRulebookSource = readFileSync(new URL('../src/app/(dashboard)/admin/rulebook/page.tsx', import.meta.url), 'utf8');
const publicRulebookSource = readFileSync(new URL('../src/app/rulebook/page.tsx', import.meta.url), 'utf8');

for (const source of [adminRulebookSource, publicRulebookSource]) {
  assert.match(source, /view_url: string/);
  assert.match(source, /download_url: string/);
  assert.match(source, /file_url\?: string \| null/);
  assert.match(source, /const rulebookUrl =/);
  assert.match(source, /path\.startsWith\('\/api\/'\) \? path\.slice\(4\) : path/);
  assert.match(source, /href=\{rulebookUrl\(rulebook\.view_url \|\| rulebook\.file_url\)\}/);
  assert.match(source, /href=\{rulebookUrl\(rulebook\.download_url\)\}/);
  assert.doesNotMatch(source, /href=\{`\$\{API_URL\}\/public\/rulebook\/(view|download)`\}/);
  assert.doesNotMatch(source, /createObjectURL|blob:/);
}

assert.match(adminRulebookSource, /file_available\?: boolean/);
assert.match(adminRulebookSource, /storage_error\?: string \| null/);
assert.match(adminRulebookSource, /Confirm that UPLOAD_STORAGE_DIR is backed by persistent storage/);
assert.match(adminRulebookSource, /admin\/storage-diagnostics/);
assert.match(adminRulebookSource, /Directory writable/);
assert.match(adminRulebookSource, /Active file exists/);

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const organizationsSource = readFileSync(new URL('../src/app/(dashboard)/admin/organizations/page.tsx', import.meta.url), 'utf8');
const scheduleSource = readFileSync(new URL('../src/app/schedule/page.tsx', import.meta.url), 'utf8');
const bracketSource = readFileSync(new URL('../src/components/TournamentBracket.tsx', import.meta.url), 'utf8');
const logoSource = readFileSync(new URL('../src/components/CommunityLogo.tsx', import.meta.url), 'utf8');

assert.match(organizationsSource, /Community Logo Upload/);
assert.match(organizationsSource, /File type: PNG only/);
assert.match(organizationsSource, /Maximum file size: 2 MB/);
assert.match(organizationsSource, /Minimum size: 500 × 500 pixels/);
assert.match(organizationsSource, /accept='image\/png,\.png'/);
assert.match(scheduleSource, /home_team_logo_url/);
assert.match(scheduleSource, /away_team_logo_url/);
assert.match(scheduleSource, /<CommunityLogo src=\{g\.home_team_logo_url\}/);
assert.match(bracketSource, /team_1_logo_url/);
assert.match(bracketSource, /team_2_logo_url/);
assert.match(bracketSource, /<CommunityLogo src=\{teamLogoUrl\(game, slot\)\}/);
assert.match(bracketSource, /<image href=/);
assert.match(logoSource, /object-contain/);
assert.match(logoSource, /logo fallback/);

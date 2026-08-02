import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { test } from 'node:test';

const clientSource = readFileSync(resolve(process.cwd(), 'src/services/api/client.ts'), 'utf8');

test('regular API requests refresh and retry exactly once after 401', () => {
  assert.match(clientSource, /response\.status === 401 && !options\.accessToken/);
  assert.equal(clientSource.match(/auth\.refreshSession\(\)/g)?.length, 1);
  assert.match(clientSource, /headers\.set\('Authorization', `Bearer \$\{refreshedAccessToken\}`\)/);
  assert.equal(clientSource.match(/response = await fetch\(url/g)?.length, 2);
});

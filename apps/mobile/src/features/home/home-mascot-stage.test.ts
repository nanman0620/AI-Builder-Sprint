import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { test } from 'node:test';

const mascotSource = readFileSync(
  resolve(process.cwd(), 'src/features/home/components/home-mascot.tsx'),
  'utf8'
);

test('모든 정적 홈 마스코트는 자연스럽게 퍼지는 방사형 연보라 stage 위에 렌더링된다', () => {
  assert.match(mascotSource, /function MascotStage/);
  assert.match(mascotSource, /RadialGradient/);
  assert.match(mascotSource, /Math\.max\(290, contentSize\)/);
  assert.match(mascotSource, /offset="0%"[\s\S]*?stopOpacity=\{0\.42\}/);
  assert.match(mascotSource, /offset="86%"[\s\S]*?stopOpacity=\{0\.06\}/);
  assert.match(mascotSource, /offset="95%"[\s\S]*?stopOpacity=\{0\.018\}/);
  assert.match(mascotSource, /offset="100%"[\s\S]*?stopOpacity=\{0\}/);
  assert.match(mascotSource, /<Circle cx=\{145\} cy=\{145\} r=\{145\}/);
  assert.ok(mascotSource.indexOf('styles.backdrop') < mascotSource.indexOf('{children}'));
});

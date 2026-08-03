import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { test } from 'node:test';

const mascotSource = readFileSync(
  resolve(process.cwd(), 'src/features/home/components/home-mascot.tsx'),
  'utf8'
);

test('홈 마스코트는 선택적으로 자연스럽게 퍼지는 방사형 연보라 stage 위에 렌더링된다', () => {
  assert.match(mascotSource, /function MascotStage/);
  assert.match(mascotSource, /RadialGradient/);
  assert.match(mascotSource, /id="mascotGroundShadow"/);
  assert.match(mascotSource, /mascotKey === 'READING' \? 0\.245 : 0\.285/);
  assert.match(mascotSource, /groundShadowOffsetRatio=\{showBackdrop \? groundShadowOffsetRatio : null\}/);
  assert.match(mascotSource, /SCORE_00: 0\.18/);
  assert.match(mascotSource, /SCORE_30: 0\.18/);
  assert.match(mascotSource, /SCORE_60: 0\.285/);
  assert.match(mascotSource, /SCORE_100: 0\.285/);
  assert.match(mascotSource, /groundShadowOffsetRatio=\{SCORE_GROUND_SHADOW_OFFSET\[scoreBand\]\}/);
  assert.match(mascotSource, /scoreBand === 'SCORE_100' \? <CompletionHeartBurst \/>/);
  assert.match(mascotSource, /<HeartParticle size=\{48\}/);
  assert.match(mascotSource, /<HeartParticle size=\{46\}/);
  assert.match(mascotSource, /d="M12 21s-7\.2-4\.35/);
  assert.match(mascotSource, /duration: 900/);
  assert.match(mascotSource, /Easing\.out\(Easing\.cubic\)/);
  assert.match(mascotSource, /inputRange: \[0, 0\.12, 0\.72, 1\]/);
  assert.match(mascotSource, /outputRange: \[0, 1, 0\.9, 0\]/);
  assert.match(mascotSource, /width: 278/);
  assert.match(mascotSource, /height: 238/);
  assert.match(mascotSource, /cy=\{stageSize \/ 2 \+ contentSize \* groundShadowOffsetRatio\}/);
  assert.match(mascotSource, /rx=\{contentSize \* 0\.34\}/);
  assert.match(mascotSource, /ry=\{contentSize \* 0\.04\}/);
  assert.match(mascotSource, /Math\.max\(contentSize, Math\.min\(290, availableWidth\)\)/);
  assert.match(mascotSource, /offset="0%"[\s\S]*?stopOpacity=\{0\.42\}/);
  assert.match(mascotSource, /offset="86%"[\s\S]*?stopOpacity=\{0\.06\}/);
  assert.match(mascotSource, /offset="95%"[\s\S]*?stopOpacity=\{0\.018\}/);
  assert.match(mascotSource, /offset="100%"[\s\S]*?stopOpacity=\{0\}/);
  assert.match(mascotSource, /showBackdrop \? \(/);
  assert.match(mascotSource, /<Circle cx=\{stageSize \/ 2\} cy=\{stageSize \/ 2\} r=\{stageSize \/ 2\}/);
  assert.ok(mascotSource.indexOf('styles.backdrop') < mascotSource.indexOf('{children}'));
});

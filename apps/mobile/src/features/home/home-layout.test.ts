import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { test } from 'node:test';

const homeScreenSource = readFileSync(
  resolve(process.cwd(), 'src/features/home/screens/home-screen.tsx'),
  'utf8'
);

test('빈 홈 상태는 음수 위치 보정 없이 스크롤 가능한 flex 구조를 사용한다', () => {
  const emptyStateStyles = homeScreenSource.slice(
    homeScreenSource.indexOf('emptyStateScroll:'),
    homeScreenSource.indexOf('bodyHeadline:')
  );
  assert.match(homeScreenSource, /style=\{styles\.emptyStateScroll\}/);
  assert.match(homeScreenSource, /contentContainerStyle=\{styles\.emptyStateContent\}/);
  assert.match(emptyStateStyles, /emptyStateContent:\s*\{[\s\S]*?flexGrow: 1/);
  assert.match(emptyStateStyles, /emptyStateBody:\s*\{[\s\S]*?justifyContent: 'center'/);
  assert.ok(
    homeScreenSource.indexOf('styles.outlineButton') < homeScreenSource.indexOf('</ScrollView>')
  );
  assert.doesNotMatch(emptyStateStyles, /translateY:\s*-/);
  assert.doesNotMatch(emptyStateStyles, /marginTop:\s*-/);
  assert.doesNotMatch(emptyStateStyles, /marginBottom:\s*-/);
});

test('IN_PROGRESS 헤더와 마스코트는 동일한 최신 percentage를 사용한다', () => {
  assert.match(
    homeScreenSource,
    /resolveProgressFeedback\(data\.progress\.percentage\)/,
  );
  assert.match(
    homeScreenSource,
    /resolveProgressMascotBand\(data\.progress\.percentage\)/,
  );
  assert.doesNotMatch(
    homeScreenSource.slice(
      homeScreenSource.indexOf('// IN_PROGRESS:'),
      homeScreenSource.indexOf('type CheckInResultBodyProps'),
    ),
    /나만의 속도로 잘 가고 있어요!`/,
  );
});

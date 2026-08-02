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
    /resolveProgressFeedback\(\{[\s\S]*?percentage: data\.progress\.percentage/,
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

test('NO_PLANS만 전용 상단 정렬 wrapper와 계획관리 CTA를 사용한다', () => {
  const noActiveCycleBranch = homeScreenSource.slice(
    homeScreenSource.indexOf("visibleState === 'NO_ACTIVE_CYCLE'"),
    homeScreenSource.indexOf("visibleState === 'NO_PLANS'"),
  );
  const noPlansBranch = homeScreenSource.slice(
    homeScreenSource.indexOf("visibleState === 'NO_PLANS'"),
    homeScreenSource.indexOf('// IN_PROGRESS:'),
  );
  const noPlansStyles = homeScreenSource.slice(
    homeScreenSource.indexOf('noPlansBody:'),
    homeScreenSource.indexOf('centerMascot:'),
  );

  assert.match(noActiveCycleBranch, /style=\{styles\.emptyStateBody\}/);
  assert.doesNotMatch(noActiveCycleBranch, /styles\.noPlansBody/);
  assert.match(noPlansBranch, /style=\{styles\.noPlansBody\}/);
  assert.match(noPlansBranch, /router\.push\('\/\(tabs\)\/plan-management'\)/);
  assert.match(noPlansStyles, /flexGrow:\s*1/);
  assert.match(noPlansStyles, /paddingTop:\s*spacing\.sm/);
  assert.match(noPlansStyles, /gap:\s*spacing\.sm/);
  assert.doesNotMatch(noPlansStyles, /justifyContent:\s*'center'/);
  assert.doesNotMatch(noPlansStyles, /(marginTop|top|translateY):\s*-/);
});

test('NO_PLANS 조정은 공용 마스코트 stage와 다른 홈 상태 분기를 변경하지 않는다', () => {
  const noPlansBranch = homeScreenSource.slice(
    homeScreenSource.indexOf("visibleState === 'NO_PLANS'"),
    homeScreenSource.indexOf('// IN_PROGRESS:'),
  );
  const inProgressBranch = homeScreenSource.slice(
    homeScreenSource.indexOf('// IN_PROGRESS:'),
    homeScreenSource.indexOf('type CheckInResultBodyProps'),
  );

  assert.match(noPlansBranch, /<HomeMascot mascotKey=\{resolveHomeMascotKey\('NO_PLANS'\)\}/);
  assert.doesNotMatch(noPlansBranch, /(mascotStage|mascotBackdrop|mascotImage)/);
  assert.doesNotMatch(inProgressBranch, /styles\.noPlansBody/);
});

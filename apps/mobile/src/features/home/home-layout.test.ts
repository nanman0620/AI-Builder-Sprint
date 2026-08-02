import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { test } from 'node:test';

const homeScreenSource = readFileSync(
  resolve(process.cwd(), 'src/features/home/screens/home-screen.tsx'),
  'utf8'
);
const homeHeaderSource = readFileSync(
  resolve(process.cwd(), 'src/features/home/components/home-header.tsx'),
  'utf8'
);
const deadlineWarningListSource = readFileSync(
  resolve(process.cwd(), 'src/features/home/components/deadline-warning-list.tsx'),
  'utf8'
);
const progressBarSource = readFileSync(
  resolve(process.cwd(), 'src/features/home/components/progress-bar.tsx'),
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
  assert.match(emptyStateStyles, /elevatedEmptyStateBody:\s*\{[\s\S]*?paddingTop: 0/);
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

test('IN_PROGRESS 응원 문구는 한 줄에서만 축소되어 상점 크기와 진행률 바 위치를 유지한다', () => {
  const inProgressBranch = homeScreenSource.slice(
    homeScreenSource.indexOf('// IN_PROGRESS:'),
    homeScreenSource.indexOf('type CheckInResultBodyProps'),
  );
  assert.match(inProgressBranch, /title=\{nickname \? `\$\{nickname\}님의 \$\{periodLabel\} 할 일` : '안녕하세요,'\}/);
  assert.match(inProgressBranch, /feedback=\{nickname \? progressFeedback/);
  assert.match(homeHeaderSource, /adjustsFontSizeToFit/);
  assert.match(homeHeaderSource, /minimumFontScale=\{0\.65\}/);
  assert.match(homeHeaderSource, /numberOfLines=\{1\}/);
  assert.match(homeHeaderSource, /feedback\.length > 28/);
  assert.match(homeHeaderSource, /feedback\.length > 22/);
  assert.match(homeHeaderSource, /feedbackCompact:\s*\{[\s\S]*?fontSize: 14/);
  assert.match(homeHeaderSource, /feedbackTight:\s*\{[\s\S]*?fontSize: 12/);
  assert.match(homeHeaderSource, /height: headerContentHeight \*\s*0\.9/);
  assert.match(homeHeaderSource, /headerRow:\s*\{[\s\S]*?position: 'relative'/);
  assert.match(homeHeaderSource, /headerContent:\s*\{[\s\S]*?minWidth: 0/);
  assert.match(homeHeaderSource, /shopButton:\s*\{[\s\S]*?position: 'absolute'[\s\S]*?right: -30/);
});

test('NO_ACTIVE_CYCLE과 NO_PLANS가 상단 정렬 wrapper와 계획관리 CTA를 사용한다', () => {
  const noActiveCycleBranch = homeScreenSource.slice(
    homeScreenSource.indexOf("visibleState === 'NO_ACTIVE_CYCLE'"),
    homeScreenSource.indexOf("visibleState === 'NO_PLANS'"),
  );
  const noPlansBranch = homeScreenSource.slice(
    homeScreenSource.indexOf("visibleState === 'NO_PLANS'"),
    homeScreenSource.indexOf('// IN_PROGRESS:'),
  );
  const elevatedEmptyStateStyles = homeScreenSource.slice(
    homeScreenSource.indexOf('elevatedEmptyStateBody:'),
    homeScreenSource.indexOf('centerMascot:'),
  );

  assert.match(noActiveCycleBranch, /style=\{styles\.elevatedEmptyStateBody\}/);
  assert.match(noPlansBranch, /style=\{styles\.elevatedEmptyStateBody\}/);
  assert.match(noActiveCycleBranch, /router\.push\('\/\(tabs\)\/plan-management'\)/);
  assert.match(noPlansBranch, /router\.push\('\/\(tabs\)\/plan-management'\)/);
  assert.match(elevatedEmptyStateStyles, /flexGrow:\s*1/);
  assert.match(elevatedEmptyStateStyles, /paddingTop:\s*0/);
  assert.match(elevatedEmptyStateStyles, /gap:\s*spacing\.sm/);
  assert.doesNotMatch(elevatedEmptyStateStyles, /justifyContent:\s*'center'/);
  assert.doesNotMatch(elevatedEmptyStateStyles, /(marginTop|top|translateY):\s*-/);
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
  assert.doesNotMatch(inProgressBranch, /styles\.elevatedEmptyStateBody/);
});

test('마감 임박 화면만 연보라 원형 배경을 숨긴다', () => {
  const deadlineWarningBranch = homeScreenSource.slice(
    homeScreenSource.indexOf("visibleState === 'DEADLINE_WARNING'"),
    homeScreenSource.indexOf("visibleState === 'NO_ACTIVE_CYCLE'"),
  );
  assert.match(deadlineWarningBranch, /showBackdrop=\{false\}/);
  assert.match(homeScreenSource, /showBackdrop=\{false\}/);
});

test('마감 시각 formatter는 배치 가능·부족 시간 값에 영향을 주지 않는다', () => {
  assert.match(deadlineWarningListSource, /formatDeadlineLabel\(item\.deadlineAt, logicalDate\)/);
  assert.match(deadlineWarningListSource, /\{item\.availableMinutes\}분/);
  assert.match(deadlineWarningListSource, /\{item\.shortageMinutes\}분/);
});

test('홈 진행 바의 100% 구름 효과는 끄고 마스코트 하트 효과만 사용한다', () => {
  assert.match(progressBarSource, /showCompletionEffect=\{false\}/);
});

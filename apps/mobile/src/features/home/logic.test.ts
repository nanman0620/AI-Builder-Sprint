// 순수 함수 테스트다. RN/Expo 의존성이 없어 로컬 tsc로 CommonJS로 컴파일한 뒤
// `node --test`로 실행할 수 있다(apps/mobile/src/features/bootstrap/route.test.ts와 동일한 방식).
import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  applyOptimisticCheckState,
  computeOptimisticProgress,
  formatLogicalDateBadge,
  formatPeriodLabel,
  PlanBlockPendingRegistry,
  PROGRESS_FEEDBACK_MESSAGES,
  replacePlanBlock,
  resolveCheckInFeedback,
  resolveHomeMascotKey,
  resolveProgressFeedback,
  resolveProgressMascotBand,
  resolveScoreBand,
  resolveVisibleHomeState,
  shouldHideTabBar,
  sortPlanBlocksByDisplayOrder,
} from './logic';
import type { HomePlanBlock } from '../bootstrap/types';

function makeBlock(overrides: Partial<HomePlanBlock> = {}): HomePlanBlock {
  return {
    id: 'block-1',
    taskId: 'task-1',
    planDate: '2026-07-29',
    period: 'AFTERNOON',
    allocatedMinutes: 60,
    allocatedAmountText: null,
    displayTitle: '기본 할 일',
    displayOrder: 1,
    status: 'PLANNED',
    checkedAt: null,
    ...overrides,
  };
}

// docs/ai/IMPLEMENTATION_CONTEXT.md 8절 "홈 우선순위" 6단계.
test('FINALIZING이 CHECK_IN_RESULT·DEADLINE_WARNING보다 우선한다', () => {
  const result = resolveVisibleHomeState({
    homeMode: 'FINALIZING',
    blockingNotice: { type: 'DEADLINE_WARNING', items: [{ taskId: 't', title: 'x', deadlineAt: '', requiredMinutes: 1, availableMinutes: 1, shortageMinutes: 0 }] },
  });
  assert.equal(result, 'FINALIZING');
});

test('CHECK_IN_RESULT가 DEADLINE_WARNING보다 우선한다', () => {
  const result = resolveVisibleHomeState({
    homeMode: 'CHECK_IN_RESULT',
    blockingNotice: { type: 'DEADLINE_WARNING', items: [{ taskId: 't', title: 'x', deadlineAt: '', requiredMinutes: 1, availableMinutes: 1, shortageMinutes: 0 }] },
  });
  assert.equal(result, 'CHECK_IN_RESULT');
});

test('blockingNotice.items가 비어 있으면 DEADLINE_WARNING을 표시하지 않는다', () => {
  const result = resolveVisibleHomeState({
    homeMode: 'IN_PROGRESS',
    blockingNotice: { type: 'DEADLINE_WARNING', items: [] },
  });
  assert.equal(result, 'IN_PROGRESS');
});

test('blockingNotice가 null이면 homeMode를 그대로 쓴다', () => {
  const result = resolveVisibleHomeState({ homeMode: 'NO_PLANS', blockingNotice: null });
  assert.equal(result, 'NO_PLANS');
});

test('blockingNotice가 있으면 homeMode가 IN_PROGRESS가 아니어도 DEADLINE_WARNING을 표시한다', () => {
  const result = resolveVisibleHomeState({
    homeMode: 'IN_PROGRESS',
    blockingNotice: { type: 'DEADLINE_WARNING', items: [{ taskId: 't', title: 'x', deadlineAt: '', requiredMinutes: 1, availableMinutes: 1, shortageMinutes: 0 }] },
  });
  assert.equal(result, 'DEADLINE_WARNING');
});

test('NO_ACTIVE_CYCLE·NO_PLANS·IN_PROGRESS는 각각 그대로 매핑된다', () => {
  assert.equal(resolveVisibleHomeState({ homeMode: 'NO_ACTIVE_CYCLE', blockingNotice: null }), 'NO_ACTIVE_CYCLE');
  assert.equal(resolveVisibleHomeState({ homeMode: 'NO_PLANS', blockingNotice: null }), 'NO_PLANS');
  assert.equal(resolveVisibleHomeState({ homeMode: 'IN_PROGRESS', blockingNotice: null }), 'IN_PROGRESS');
});

test('하단 탭 숨김 대상은 FINALIZING·CHECK_IN_RESULT·DEADLINE_WARNING뿐이다', () => {
  assert.equal(shouldHideTabBar('FINALIZING'), true);
  assert.equal(shouldHideTabBar('CHECK_IN_RESULT'), true);
  assert.equal(shouldHideTabBar('DEADLINE_WARNING'), true);
  assert.equal(shouldHideTabBar('NO_ACTIVE_CYCLE'), false);
  assert.equal(shouldHideTabBar('NO_PLANS'), false);
  assert.equal(shouldHideTabBar('IN_PROGRESS'), false);
});

// UI_REFERENCE.md 점수별 마스코트 선택 규칙 경계값: 0/29/30/59/60/99/100.
test('점수 구간 경계값이 정확히 나뉜다', () => {
  assert.equal(resolveScoreBand(0), 'SCORE_00');
  assert.equal(resolveScoreBand(29), 'SCORE_00');
  assert.equal(resolveScoreBand(30), 'SCORE_30');
  assert.equal(resolveScoreBand(59), 'SCORE_30');
  assert.equal(resolveScoreBand(60), 'SCORE_60');
  assert.equal(resolveScoreBand(99), 'SCORE_60');
  assert.equal(resolveScoreBand(100), 'SCORE_100');
});

test('CheckIn 결과 문구가 점수 구간 경계마다 정확히 바뀐다', () => {
  assert.equal(resolveCheckInFeedback(0, false), '괜찮아요, 다시 이어가면 돼요');
  assert.equal(resolveCheckInFeedback(29, false), '괜찮아요, 다시 이어가면 돼요');
  assert.equal(resolveCheckInFeedback(30, false), '좋아요, 흐름을 만들고 있어요');
  assert.equal(resolveCheckInFeedback(59, false), '좋아요, 흐름을 만들고 있어요');
  assert.equal(resolveCheckInFeedback(60, false), '잘하고 있어요, 이 흐름 그대로!');
  assert.equal(resolveCheckInFeedback(99, false), '잘하고 있어요, 이 흐름 그대로!');
  assert.equal(resolveCheckInFeedback(100, false), '오늘 계획을 모두 이어냈어요!');
  assert.equal(resolveCheckInFeedback(101, false), '오늘 계획을 모두 이어냈어요!');
});

test('IN_PROGRESS 후보는 구간마다 blank와 중복 없이 정확히 6개다', () => {
  for (const messages of Object.values(PROGRESS_FEEDBACK_MESSAGES)) {
    assert.equal(messages.length, 6);
    assert.equal(new Set(messages).size, 6);
    assert.equal(messages.every((message) => message.trim().length > 0), true);
  }
  assert.equal(
    Object.values(PROGRESS_FEEDBACK_MESSAGES).flat().includes('괜찮아요, 다시 이어가면 돼요'),
    false,
  );
});

test('IN_PROGRESS 문구가 percentage 경계의 올바른 후보 구간을 따른다', () => {
  const cases = [
    [0, 'SCORE_00'], [29, 'SCORE_00'], [30, 'SCORE_30'], [59, 'SCORE_30'],
    [60, 'SCORE_60'], [99, 'SCORE_60'], [100, 'SCORE_100'], [120, 'SCORE_100'],
  ] as const;
  for (const [percentage, band] of cases) {
    const message = resolveProgressFeedback({
      percentage,
      logicalDate: '2026-08-02',
      currentPeriod: 'AFTERNOON',
      completedPlanCount: 2,
      totalPlanCount: 4,
    });
    assert.equal(PROGRESS_FEEDBACK_MESSAGES[band].includes(message), true);
  }
});

test('IN_PROGRESS 문구 선택은 동일 상태에서 결정적이고 체크 상태 변경 후에도 해당 구간 후보다', () => {
  const input = {
    percentage: 50,
    logicalDate: '2026-08-02',
    currentPeriod: 'AFTERNOON' as const,
    completedPlanCount: 2,
    totalPlanCount: 4,
  };
  const first = resolveProgressFeedback(input);
  assert.equal(resolveProgressFeedback(input), first);
  assert.equal(resolveProgressFeedback(input), first);

  const changed = resolveProgressFeedback({ ...input, completedPlanCount: 3 });
  assert.equal(PROGRESS_FEEDBACK_MESSAGES.SCORE_30.includes(changed), true);
});

test('IN_PROGRESS 경계 전환 시 이전 구간 후보가 남지 않는다', () => {
  const resolve = (percentage: number) => resolveProgressFeedback({
    percentage,
    logicalDate: '2026-08-02',
    currentPeriod: 'EVENING',
    completedPlanCount: percentage,
    totalPlanCount: 100,
  });
  assert.equal(PROGRESS_FEEDBACK_MESSAGES.SCORE_30.includes(resolve(30)), true);
  assert.equal(PROGRESS_FEEDBACK_MESSAGES.SCORE_60.includes(resolve(60)), true);
  assert.equal(PROGRESS_FEEDBACK_MESSAGES.SCORE_100.includes(resolve(100)), true);
});

test('cycle이 끝나면 점수와 관계없이 7일 계획 종료 문구가 우선한다', () => {
  const cycleEndMessage = '7일의 계획이 모두 끝났어요';
  assert.equal(resolveCheckInFeedback(0, true), cycleEndMessage);
  assert.equal(resolveCheckInFeedback(30, true), cycleEndMessage);
  assert.equal(resolveCheckInFeedback(60, true), cycleEndMessage);
  assert.equal(resolveCheckInFeedback(100, true), cycleEndMessage);
});

test('홈 진행률 경계값이 0·30·60·100 단계 마스코트에 정확히 매핑된다', () => {
  assert.equal(resolveProgressMascotBand(0), 'SCORE_00');
  assert.equal(resolveProgressMascotBand(29), 'SCORE_00');
  assert.equal(resolveProgressMascotBand(30), 'SCORE_30');
  assert.equal(resolveProgressMascotBand(59), 'SCORE_30');
  assert.equal(resolveProgressMascotBand(60), 'SCORE_60');
  assert.equal(resolveProgressMascotBand(99), 'SCORE_60');
  assert.equal(resolveProgressMascotBand(100), 'SCORE_100');
});

test('마스코트 매핑: DEADLINE_WARNING=SAD, NO_ACTIVE_CYCLE=READING, 나머지=DEFAULT', () => {
  assert.equal(resolveHomeMascotKey('DEADLINE_WARNING'), 'SAD');
  assert.equal(resolveHomeMascotKey('NO_ACTIVE_CYCLE'), 'READING');
  assert.equal(resolveHomeMascotKey('NO_PLANS'), 'DEFAULT');
  assert.equal(resolveHomeMascotKey('IN_PROGRESS'), 'DEFAULT');
  assert.equal(resolveHomeMascotKey('FINALIZING'), 'DEFAULT');
});

test('period 라벨 변환', () => {
  assert.equal(formatPeriodLabel('MORNING'), '오전');
  assert.equal(formatPeriodLabel('AFTERNOON'), '오후');
  assert.equal(formatPeriodLabel('EVENING'), '저녁');
});

test('displayOrder 기준 정렬은 원본 배열을 바꾸지 않는다', () => {
  const blocks = [makeBlock({ id: 'b', displayOrder: 2 }), makeBlock({ id: 'a', displayOrder: 1 })];
  const sorted = sortPlanBlocksByDisplayOrder(blocks);
  assert.deepEqual(sorted.map((b) => b.id), ['a', 'b']);
  assert.deepEqual(blocks.map((b) => b.id), ['b', 'a']);
});

test('optimistic 체크는 해당 id만 바꾸고 displayTitle 등 나머지 필드는 유지한다', () => {
  const blocks = [makeBlock({ id: 'a', status: 'PLANNED' }), makeBlock({ id: 'b', status: 'PLANNED' })];
  const next = applyOptimisticCheckState(blocks, 'a', true, '2026-07-29T10:00:00+09:00');
  assert.equal(next[0].status, 'CHECKED');
  assert.equal(next[0].checkedAt, '2026-07-29T10:00:00+09:00');
  assert.equal(next[0].displayTitle, blocks[0].displayTitle);
  assert.equal(next[1].status, 'PLANNED');
});

test('optimistic 체크 해제는 checkedAt을 null로 되돌린다', () => {
  const blocks = [makeBlock({ id: 'a', status: 'CHECKED', checkedAt: '2026-07-29T10:00:00+09:00' })];
  const next = applyOptimisticCheckState(blocks, 'a', false, '2026-07-29T11:00:00+09:00');
  assert.equal(next[0].status, 'PLANNED');
  assert.equal(next[0].checkedAt, null);
});

test('optimistic progress는 checked/total 개수 기준이다(시간 비율 아님)', () => {
  const blocks = [
    makeBlock({ id: 'a', status: 'CHECKED' }),
    makeBlock({ id: 'b', status: 'CHECKED' }),
    makeBlock({ id: 'c', status: 'PLANNED' }),
  ];
  assert.deepEqual(computeOptimisticProgress(blocks), { checkedCount: 2, totalCount: 3, percentage: 67 });
});

test('optimistic progress는 PlanBlock이 없으면 0%다', () => {
  assert.deepEqual(computeOptimisticProgress([]), { checkedCount: 0, totalCount: 0, percentage: 0 });
});

test('pending registry는 동일 PlanBlock의 연속 요청만 거부한다', () => {
  const registry = new PlanBlockPendingRegistry();
  const tokenA = registry.begin('a');
  const tokenB = registry.begin('b');

  assert.ok(tokenA);
  assert.ok(tokenB);
  assert.equal(registry.begin('a'), null);
  assert.equal(registry.owns('a', tokenA), true);
  assert.equal(registry.owns('b', tokenB), true);
});

test('이전 요청 token은 이후 요청의 pending을 해제할 수 없다', () => {
  const registry = new PlanBlockPendingRegistry();
  const oldToken = registry.begin('a');
  assert.ok(oldToken);
  assert.equal(registry.finish('a', oldToken), true);

  const newToken = registry.begin('a');
  assert.ok(newToken);
  assert.equal(registry.finish('a', oldToken), false);
  assert.equal(registry.owns('a', newToken), true);
});

test('reset은 이전 token의 소유권을 무효화한다', () => {
  const registry = new PlanBlockPendingRegistry();
  const oldToken = registry.begin('a');
  assert.ok(oldToken);

  registry.clear();
  const newToken = registry.begin('a');
  assert.ok(newToken);
  assert.equal(registry.owns('a', oldToken), false);
  assert.equal(registry.owns('a', newToken), true);
});

test('서로 다른 PlanBlock 응답을 역순 병합해도 두 상태와 진행률을 유지한다', () => {
  let blocks = [makeBlock({ id: 'a' }), makeBlock({ id: 'b' })];
  blocks = applyOptimisticCheckState(blocks, 'a', true, '2026-07-29T10:00:00+09:00');
  blocks = applyOptimisticCheckState(blocks, 'b', true, '2026-07-29T10:00:01+09:00');

  blocks = replacePlanBlock(
    blocks,
    makeBlock({ id: 'b', status: 'CHECKED', checkedAt: '2026-07-29T10:00:03+09:00' })
  );
  blocks = replacePlanBlock(
    blocks,
    makeBlock({ id: 'a', status: 'CHECKED', checkedAt: '2026-07-29T10:00:02+09:00' })
  );

  assert.deepEqual(blocks.map((block) => block.status), ['CHECKED', 'CHECKED']);
  assert.deepEqual(computeOptimisticProgress(blocks), {
    checkedCount: 2,
    totalCount: 2,
    percentage: 100,
  });
});

test('A 성공 후 B 실패 rollback은 B만 복원한다', () => {
  const originalB = makeBlock({ id: 'b' });
  let blocks = [makeBlock({ id: 'a' }), originalB];
  blocks = applyOptimisticCheckState(blocks, 'a', true, '2026-07-29T10:00:00+09:00');
  blocks = applyOptimisticCheckState(blocks, 'b', true, '2026-07-29T10:00:01+09:00');
  blocks = replacePlanBlock(
    blocks,
    makeBlock({ id: 'a', status: 'CHECKED', checkedAt: '2026-07-29T10:00:02+09:00' })
  );
  blocks = replacePlanBlock(blocks, originalB);

  assert.deepEqual(blocks.map((block) => block.status), ['CHECKED', 'PLANNED']);
  assert.deepEqual(computeOptimisticProgress(blocks), {
    checkedCount: 1,
    totalCount: 2,
    percentage: 50,
  });
});

test('A 실패 후 B 성공이어도 늦은 A rollback이 B를 덮지 않는다', () => {
  const originalA = makeBlock({ id: 'a' });
  let blocks = [originalA, makeBlock({ id: 'b' })];
  blocks = applyOptimisticCheckState(blocks, 'a', true, '2026-07-29T10:00:00+09:00');
  blocks = applyOptimisticCheckState(blocks, 'b', true, '2026-07-29T10:00:01+09:00');
  blocks = replacePlanBlock(
    blocks,
    makeBlock({ id: 'b', status: 'CHECKED', checkedAt: '2026-07-29T10:00:02+09:00' })
  );
  blocks = replacePlanBlock(blocks, originalA);

  assert.deepEqual(blocks.map((block) => block.status), ['PLANNED', 'CHECKED']);
  assert.deepEqual(computeOptimisticProgress(blocks), {
    checkedCount: 1,
    totalCount: 2,
    percentage: 50,
  });
});

test('logicalDate 배지 포맷은 기기 로컬 타임존과 무관하게 같은 날짜를 표시한다', () => {
  assert.equal(formatLogicalDateBadge('2026-07-26'), '7월 26일 일요일');
  assert.equal(formatLogicalDateBadge('2026-01-01'), '1월 1일 목요일');
});

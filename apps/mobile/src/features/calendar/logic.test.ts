import assert from 'node:assert/strict';
import test from 'node:test';

import {
  CalendarRequestOwnership,
  formatSegmentTime,
  getAdjacentMonthRange,
  getCompletedCount,
  getMonthRange,
  getVisibleCheckIn,
  getVisiblePlanBlocks,
  hasDayData,
  hasOnlyFuturePeriods,
  isDayEmpty,
  listMonthDates,
  sortFixedSchedules,
  sortPeriods,
} from './logic';
import type { CalendarDay, CalendarPeriodData } from './types';

function makePeriod(overrides: Partial<CalendarPeriodData> = {}): CalendarPeriodData {
  return {
    period: 'MORNING',
    temporalState: 'PAST',
    checkIn: null,
    planBlocks: [],
    fixedSchedules: [],
    ...overrides,
  };
}

test('과거 CheckIn 점수와 실제 score=0을 null과 구분해 보존한다', () => {
  const zero = makePeriod({
    checkIn: {
      id: 'check-0',
      score: 0,
      totalPlanCount: 2,
      completedPlanCount: 0,
      finalizedAt: '2026-07-25T12:00:00+09:00',
    },
  });
  assert.equal(getVisibleCheckIn(zero)?.score, 0);
  assert.equal(getVisibleCheckIn(makePeriod()), null);
  assert.equal(getVisibleCheckIn({ ...zero, temporalState: 'CURRENT' }), null);
});

test('현재 날짜의 과거·현재·미래 분기를 정해진 순서로 정렬한다', () => {
  const periods = [
    makePeriod({ period: 'EVENING', temporalState: 'FUTURE' }),
    makePeriod({ period: 'MORNING', temporalState: 'PAST' }),
    makePeriod({ period: 'AFTERNOON', temporalState: 'CURRENT' }),
  ];
  assert.deepEqual(sortPeriods(periods).map((item) => item.period), [
    'MORNING',
    'AFTERNOON',
    'EVENING',
  ]);
});

test('temporalState별 PlanBlock을 필터링하고 displayOrder로 정렬한다', () => {
  const blocks = [
    { id: 'later', displayTitle: '그대로 표시 2', status: 'COMPLETED' as const, displayOrder: 2 },
    { id: 'hidden', displayTitle: '숨김', status: 'NOT_DONE' as const, displayOrder: 0 },
    { id: 'first', displayTitle: '그대로 표시 1', status: 'COMPLETED' as const, displayOrder: 1 },
  ];
  const visible = getVisiblePlanBlocks(makePeriod({ planBlocks: blocks }));
  assert.deepEqual(visible.map((block) => block.id), ['first', 'later']);
  assert.equal(visible[0].displayTitle, '그대로 표시 1');
  assert.deepEqual(blocks.map((block) => block.id), ['later', 'hidden', 'first']);

  assert.deepEqual(
    getVisiblePlanBlocks(
      makePeriod({
        temporalState: 'CURRENT',
        planBlocks: [
          { id: 'planned', displayTitle: 'P', status: 'PLANNED', displayOrder: 2 },
          { id: 'checked', displayTitle: 'C', status: 'CHECKED', displayOrder: 1 },
          { id: 'done', displayTitle: 'D', status: 'COMPLETED', displayOrder: 0 },
        ],
      })
    ).map((block) => block.id),
    ['checked', 'planned']
  );

  const allStatuses = [
    { id: 'planned', displayTitle: 'P', status: 'PLANNED' as const, displayOrder: 4 },
    { id: 'checked', displayTitle: 'C', status: 'CHECKED' as const, displayOrder: 3 },
    { id: 'completed', displayTitle: 'D', status: 'COMPLETED' as const, displayOrder: 2 },
    { id: 'not-done', displayTitle: 'N', status: 'NOT_DONE' as const, displayOrder: 1 },
  ];
  assert.deepEqual(
    getVisiblePlanBlocks(makePeriod({ temporalState: 'PAST', planBlocks: allStatuses })).map(
      (block) => block.id
    ),
    ['completed']
  );
  assert.deepEqual(
    getVisiblePlanBlocks(makePeriod({ temporalState: 'CURRENT', planBlocks: allStatuses })).map(
      (block) => block.id
    ),
    ['checked', 'planned']
  );
  assert.deepEqual(
    getVisiblePlanBlocks(makePeriod({ temporalState: 'FUTURE', planBlocks: allStatuses })).map(
      (block) => block.id
    ),
    ['planned']
  );
});

test('blur 후 A가 늦게 끝나도 재진입 요청 B의 상태와 소유권을 변경하지 않는다', () => {
  const ownership = new CalendarRequestOwnership();
  const requestA = ownership.begin();
  assert.ok(requestA);
  assert.equal(ownership.begin(), null, '동일 focus의 중복 GET·재시도는 소유권을 얻지 못한다');

  const state = {
    data: 'initial',
    error: null as string | null,
    isLoading: true,
  };

  ownership.invalidateFocus();
  const requestB = ownership.begin();
  assert.ok(requestB);
  assert.equal(ownership.begin(), null, 'B 진행 중에도 중복 요청은 차단된다');

  // A의 then/catch/finally가 실행되는 상황을 소유권 검사로 재현한다.
  if (ownership.isOwner(requestA)) {
    state.data = 'stale-a';
    state.error = 'stale-a-error';
    state.isLoading = false;
  }
  assert.deepEqual(state, { data: 'initial', error: null, isLoading: true });
  assert.equal(ownership.finish(requestA), false, 'A는 B의 in-flight 소유 상태를 비울 수 없다');
  assert.equal(ownership.isOwner(requestB), true);
  assert.equal(state.isLoading, true, 'A가 끝나도 B의 loading은 유지된다');

  if (ownership.isOwner(requestB)) {
    state.data = 'latest-b';
    state.error = null;
    state.isLoading = false;
  }
  assert.equal(ownership.finish(requestB), true);
  assert.deepEqual(state, { data: 'latest-b', error: null, isLoading: false });

  const retryAfterB = ownership.begin();
  assert.ok(retryAfterB, 'B가 끝난 뒤에만 다음 요청이 소유권을 얻는다');
});

test('미래 PlanBlock과 고정 일정은 표시 데이터이며 미래 통계는 숨긴다', () => {
  const day: CalendarDay = {
    date: '2026-07-31',
    periods: [
      makePeriod({
        temporalState: 'FUTURE',
        planBlocks: [{ id: 'p', displayTitle: '미래 계획', status: 'PLANNED', displayOrder: 0 }],
        fixedSchedules: [
          {
            id: 'f',
            title: '일정',
            startAt: '2026-07-31T10:00:00+09:00',
            endAt: '2026-07-31T11:00:00+09:00',
            segmentStartAt: '2026-07-31T10:00:00+09:00',
            segmentEndAt: '2026-07-31T11:00:00+09:00',
          },
        ],
      }),
    ],
  };
  assert.equal(hasDayData(day), true);
  assert.equal(hasOnlyFuturePeriods(day), true);
});

test('fixedSchedule만, CheckIn만 있는 날짜에는 점을 표시하고 완전한 빈 날짜만 비운다', () => {
  const scheduleOnly: CalendarDay = {
    date: '2026-07-01',
    periods: [
      makePeriod({
        fixedSchedules: [
          {
            id: 'f',
            title: '일정',
            startAt: '2026-07-01T10:00:00+09:00',
            endAt: '2026-07-01T11:00:00+09:00',
            segmentStartAt: '2026-07-01T10:00:00+09:00',
            segmentEndAt: '2026-07-01T11:00:00+09:00',
          },
        ],
      }),
    ],
  };
  const checkInOnly: CalendarDay = {
    date: '2026-07-02',
    periods: [
      makePeriod({
        checkIn: {
          id: 'c',
          score: 75,
          totalPlanCount: 2,
          completedPlanCount: 2,
          finalizedAt: '2026-07-02T12:00:00+09:00',
        },
      }),
    ],
  };
  const empty: CalendarDay = { date: '2026-07-03', periods: [makePeriod()] };
  assert.equal(hasDayData(scheduleOnly), true);
  assert.equal(hasDayData(checkInOnly), true);
  assert.equal(isDayEmpty(empty), true);
});

test('완료 개수는 과거 COMPLETED와 현재 CHECKED만 합산하고 미래는 제외한다', () => {
  const day: CalendarDay = {
    date: '2026-07-25',
    periods: [
      makePeriod({
        temporalState: 'PAST',
        checkIn: {
          id: 'a',
          score: 50,
          totalPlanCount: 3,
          completedPlanCount: 99,
          finalizedAt: '2026-07-25T12:00:00+09:00',
        },
        planBlocks: [
          { id: 'past-completed', displayTitle: '완료', status: 'COMPLETED', displayOrder: 0 },
          { id: 'past-not-done', displayTitle: '미완료', status: 'NOT_DONE', displayOrder: 1 },
          { id: 'past-checked', displayTitle: '잘못 남은 체크', status: 'CHECKED', displayOrder: 2 },
        ],
      }),
      makePeriod({
        period: 'AFTERNOON',
        temporalState: 'CURRENT',
        planBlocks: [
          { id: 'current-checked', displayTitle: '오늘 체크', status: 'CHECKED', displayOrder: 0 },
          { id: 'current-planned', displayTitle: '오늘 예정', status: 'PLANNED', displayOrder: 1 },
        ],
      }),
      makePeriod({
        period: 'EVENING',
        temporalState: 'FUTURE',
        planBlocks: [
          { id: 'future-planned', displayTitle: '미래 예정', status: 'PLANNED', displayOrder: 0 },
          { id: 'future-checked', displayTitle: '미래 비정상 체크', status: 'CHECKED', displayOrder: 1 },
        ],
      }),
    ],
  };
  assert.equal(getCompletedCount(day), 2);
});

test('현재 CHECKED 1개는 1개 완료이고 체크 해제 후 PLANNED이면 다시 0개다', () => {
  const checkedDay: CalendarDay = {
    date: '2026-07-25',
    periods: [
      makePeriod({
        temporalState: 'CURRENT',
        planBlocks: [{ id: 'today', displayTitle: '오늘 계획', status: 'CHECKED', displayOrder: 0 }],
      }),
    ],
  };

  assert.equal(getCompletedCount(checkedDay), 1);
  assert.equal(
    getCompletedCount({
      ...checkedDay,
      periods: [
        { ...checkedDay.periods[0], planBlocks: [{ ...checkedDay.periods[0].planBlocks[0], status: 'PLANNED' }] },
      ],
    }),
    0
  );
});

test('고정 일정은 segmentStartAt 순으로 정렬하고 초를 제외한다', () => {
  const schedules = [
    {
      id: 'b',
      title: '늦은 일정',
      startAt: '',
      endAt: '',
      segmentStartAt: '2026-07-01T13:30:00+09:00',
      segmentEndAt: '2026-07-01T14:00:00+09:00',
    },
    {
      id: 'a',
      title: '이른 일정',
      startAt: '',
      endAt: '',
      segmentStartAt: '2026-07-01T09:05:00+09:00',
      segmentEndAt: '2026-07-01T10:00:00+09:00',
    },
  ];
  assert.deepEqual(sortFixedSchedules(schedules).map((item) => item.id), ['a', 'b']);
  assert.equal(formatSegmentTime(schedules[1].segmentStartAt), '09:05');
});

test('월 경계와 윤년 범위를 정확히 계산한다', () => {
  assert.deepEqual(getMonthRange(2024, 1), { from: '2024-02-01', to: '2024-02-29' });
  assert.equal(listMonthDates({ from: '2024-02-01', to: '2024-02-29' }).length, 29);
  assert.deepEqual(getAdjacentMonthRange({ from: '2026-12-01', to: '2026-12-31' }, 1), {
    from: '2027-01-01',
    to: '2027-01-31',
  });
});

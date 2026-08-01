import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { SolarRequestItem } from '../types';
import { getRequestItemCardDisplay } from './request-item-card-display';

function makeItem(overrides: Partial<SolarRequestItem> = {}): SolarRequestItem {
  return {
    id: 'item-1',
    itemOrder: 1,
    action: 'CREATE',
    actionLabel: '추가',
    entityType: 'TASK',
    entityLabel: '할 일',
    status: 'READY',
    statusLabel: '준비됨',
    rawLineText: '발표 대본 읽기',
    title: '발표 대본 읽기',
    summaryText: '준비됨 · 30분',
    normalizedPayload: null,
    missingFields: [],
    pendingQuestion: null,
    targetEntityId: null,
    targetSnapshot: null,
    ...overrides,
  };
}

test('추가 Task는 기존 할 일 배지와 준비됨 요약을 유지한다', () => {
  assert.deepEqual(getRequestItemCardDisplay(makeItem()), {
    badgeLabel: '할 일',
    summaryText: '준비됨 · 30분',
    isDelete: false,
  });
});

test('삭제 Task는 삭제 배지와 삭제 예정 문구를 표시한다', () => {
  const display = getRequestItemCardDisplay(
    makeItem({ action: 'DELETE', actionLabel: '삭제', targetEntityId: 'task-1' })
  );

  assert.deepEqual(display, {
    badgeLabel: '삭제',
    summaryText: '삭제 예정',
    isDelete: true,
  });
});

test('추가와 여러 삭제 대상은 배열에서 제거되지 않고 각각의 정책을 유지한다', () => {
  const items = [
    makeItem(),
    makeItem({ id: 'item-2', itemOrder: 2, action: 'DELETE', actionLabel: '삭제' }),
    makeItem({ id: 'item-3', itemOrder: 3, action: 'DELETE', actionLabel: '삭제' }),
  ];

  assert.deepEqual(items.map(getRequestItemCardDisplay), [
    { badgeLabel: '할 일', summaryText: '준비됨 · 30분', isDelete: false },
    { badgeLabel: '삭제', summaryText: '삭제 예정', isDelete: true },
    { badgeLabel: '삭제', summaryText: '삭제 예정', isDelete: true },
  ]);
});

test('삭제 FixedSchedule에도 동일한 삭제 표시 정책을 적용한다', () => {
  const display = getRequestItemCardDisplay(
    makeItem({
      action: 'DELETE',
      actionLabel: '삭제',
      entityType: 'FIXED_SCHEDULE',
      entityLabel: '고정 일정',
      summaryText: '준비됨 · 8월 2일 13:00-8월 2일 14:00',
    })
  );

  assert.deepEqual(display, {
    badgeLabel: '삭제',
    summaryText: '삭제 예정',
    isDelete: true,
  });
});

test('삭제 요청이 취소되어 CREATE 카드로 남은 항목에는 삭제 표시를 하지 않는다', () => {
  const display = getRequestItemCardDisplay(
    makeItem({ action: 'CREATE', actionLabel: '추가', entityType: 'FIXED_SCHEDULE', entityLabel: '고정 일정' })
  );

  assert.equal(display.isDelete, false);
  assert.equal(display.badgeLabel, '고정 일정');
  assert.equal(display.summaryText, '준비됨 · 30분');
});

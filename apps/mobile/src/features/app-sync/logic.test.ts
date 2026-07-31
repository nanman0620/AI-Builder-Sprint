import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  ExecutionTerminalTracker,
  getNextSeoulBoundary,
  getSeoulLogicalSnapshot,
} from './logic';

test('03:59:59 KST는 전날 EVENING이고 다음 경계는 같은 날 04:00이다', () => {
  const now = new Date('2026-07-30T03:59:59+09:00');
  assert.deepEqual(getSeoulLogicalSnapshot(now), {
    logicalDate: '2026-07-29',
    period: 'EVENING',
  });
  assert.equal(getNextSeoulBoundary(now).toISOString(), '2026-07-29T19:00:00.000Z');
});

test('04:00 KST는 당일 MORNING이고 다음 경계는 12:00이다', () => {
  const now = new Date('2026-07-30T04:00:00+09:00');
  assert.deepEqual(getSeoulLogicalSnapshot(now), {
    logicalDate: '2026-07-30',
    period: 'MORNING',
  });
  assert.equal(getNextSeoulBoundary(now).toISOString(), '2026-07-30T03:00:00.000Z');
});

test('11:59:59→12:00 경계에서 MORNING이 AFTERNOON으로 바뀐다', () => {
  assert.equal(
    getSeoulLogicalSnapshot(new Date('2026-07-30T11:59:59+09:00')).period,
    'MORNING'
  );
  assert.equal(
    getSeoulLogicalSnapshot(new Date('2026-07-30T12:00:00+09:00')).period,
    'AFTERNOON'
  );
});

test('17:59:59→18:00 경계에서 AFTERNOON이 EVENING으로 바뀐다', () => {
  assert.equal(
    getSeoulLogicalSnapshot(new Date('2026-07-30T17:59:59+09:00')).period,
    'AFTERNOON'
  );
  assert.equal(
    getSeoulLogicalSnapshot(new Date('2026-07-30T18:00:00+09:00')).period,
    'EVENING'
  );
});

test('02:00 KST는 전날 logicalDate의 EVENING이다', () => {
  assert.deepEqual(getSeoulLogicalSnapshot(new Date('2026-07-30T02:00:00+09:00')), {
    logicalDate: '2026-07-29',
    period: 'EVENING',
  });
});

test('exact boundary에서 다음 경계는 현재 시각보다 뒤다', () => {
  for (const value of [
    '2026-07-30T04:00:00+09:00',
    '2026-07-30T12:00:00+09:00',
    '2026-07-30T18:00:00+09:00',
  ]) {
    const now = new Date(value);
    assert.ok(getNextSeoulBoundary(now).getTime() > now.getTime());
  }
});

test('같은 execution terminal 결과는 한 번만 처리한다', () => {
  const tracker = new ExecutionTerminalTracker();
  assert.equal(tracker.shouldHandle('request-1', 'COMPLETED'), true);
  assert.equal(tracker.shouldHandle('request-1', 'COMPLETED'), false);
  assert.equal(tracker.shouldHandle('request-2', 'FAILED'), true);
  tracker.reset();
  assert.equal(tracker.shouldHandle('request-2', 'FAILED'), true);
});

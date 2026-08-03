import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { test } from 'node:test';

const calendarSource = readFileSync(
  resolve(process.cwd(), 'src/features/calendar/screens/calendar-screen.tsx'),
  'utf8'
);

test('선택 날짜는 숫자 typography를 바꾸지 않고 배경과 색상으로만 구분한다', () => {
  assert.match(calendarSource, /dayNumberCircleSelected:\s*\{ backgroundColor: colors\.primary \}/);
  assert.match(calendarSource, /dayNumberSelected:\s*\{ color: colors\.background \}/);
  assert.doesNotMatch(calendarSource, /dayNumberSelected:\s*\{[^}]*font(Size|Family|Weight)/);
  assert.match(calendarSource, /dayDot:/);
});

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { test } from 'node:test';

const homePlanRowSource = readFileSync(
  resolve(process.cwd(), 'src/features/home/components/plan-block-row.tsx'),
  'utf8'
);
const calendarSource = readFileSync(
  resolve(process.cwd(), 'src/features/calendar/screens/calendar-screen.tsx'),
  'utf8'
);

test('홈과 캘린더 PlanBlock은 같은 시각 token을 사용하고 고정 일정 스타일은 유지한다', () => {
  assert.match(homePlanRowSource, /planBlockVisuals\.borderColor/);
  assert.match(homePlanRowSource, /planBlockVisuals\.checkSize/);
  assert.match(calendarSource, /planBlockVisuals\.borderColor/);
  assert.match(calendarSource, /planBlockVisuals\.checkSize/);
  assert.match(calendarSource, /scheduleCard:\s*\{[\s\S]*?borderWidth: 2/);
  assert.match(calendarSource, /scheduleCard:\s*\{[\s\S]*?borderColor: colors\.primary/);
});

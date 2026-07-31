import type { PlanPeriod } from '../bootstrap/types';

const SEOUL_OFFSET_MS = 9 * 60 * 60 * 1000;

export type SeoulLogicalSnapshot = {
  logicalDate: string;
  period: PlanPeriod;
};

function formatUtcDate(date: Date): string {
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, '0');
  const day = String(date.getUTCDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

// Date를 UTC+09:00만큼 옮긴 뒤 UTC getter를 사용해 기기 timezone과 무관한 서울 벽시각을 얻는다.
// Asia/Seoul은 DST가 없으므로 MVP 계약의 고정 UTC+09:00 계산을 그대로 적용한다.
export function getSeoulLogicalSnapshot(now: Date): SeoulLogicalSnapshot {
  const seoulWallClock = new Date(now.getTime() + SEOUL_OFFSET_MS);
  const hour = seoulWallClock.getUTCHours();

  if (hour < 4) {
    const previousDate = new Date(seoulWallClock.getTime());
    previousDate.setUTCDate(previousDate.getUTCDate() - 1);
    return { logicalDate: formatUtcDate(previousDate), period: 'EVENING' };
  }
  if (hour < 12) {
    return { logicalDate: formatUtcDate(seoulWallClock), period: 'MORNING' };
  }
  if (hour < 18) {
    return { logicalDate: formatUtcDate(seoulWallClock), period: 'AFTERNOON' };
  }
  return { logicalDate: formatUtcDate(seoulWallClock), period: 'EVENING' };
}

export function getNextSeoulBoundary(now: Date): Date {
  const seoulWallClock = new Date(now.getTime() + SEOUL_OFFSET_MS);
  const year = seoulWallClock.getUTCFullYear();
  const month = seoulWallClock.getUTCMonth();
  const day = seoulWallClock.getUTCDate();
  const hour = seoulWallClock.getUTCHours();

  let boundaryHour: number;
  let dayOffset = 0;
  if (hour < 4) {
    boundaryHour = 4;
  } else if (hour < 12) {
    boundaryHour = 12;
  } else if (hour < 18) {
    boundaryHour = 18;
  } else {
    boundaryHour = 4;
    dayOffset = 1;
  }

  const boundaryWallClock = Date.UTC(year, month, day + dayOffset, boundaryHour);
  return new Date(boundaryWallClock - SEOUL_OFFSET_MS);
}

export function isSameSeoulLogicalSnapshot(
  left: SeoulLogicalSnapshot,
  right: SeoulLogicalSnapshot
): boolean {
  return left.logicalDate === right.logicalDate && left.period === right.period;
}

// 같은 terminal 응답이 focus·poll·foreground 경로에서 반복 관측돼도 invalidation은 한 번만 허용한다.
export class ExecutionTerminalTracker {
  private handledKey: string | null = null;

  shouldHandle(requestId: string, status: 'COMPLETED' | 'FAILED'): boolean {
    const key = `${requestId}:${status}`;
    if (this.handledKey === key) {
      return false;
    }
    this.handledKey = key;
    return true;
  }

  reset(): void {
    this.handledKey = null;
  }
}

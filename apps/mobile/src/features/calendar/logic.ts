import type {
  CalendarDateRange,
  CalendarDay,
  CalendarFixedSchedule,
  CalendarPeriod,
  CalendarPeriodData,
  CalendarPlanBlock,
} from './types';

export const PERIOD_ORDER: CalendarPeriod[] = ['MORNING', 'AFTERNOON', 'EVENING'];

export type CalendarRequestTicket = {
  focusEpoch: number;
  requestId: number;
};

// React hook 밖에서도 요청 경쟁 조건을 검증할 수 있도록 소유권 판정만 분리한다.
// 같은 focus에서는 하나의 요청만 소유권을 얻고, blur가 epoch를 바꾸면 이전 ticket은
// data/error/loading/in-flight 정리 권한을 모두 잃는다.
export class CalendarRequestOwnership {
  private focusEpoch = 0;
  private nextRequestId = 0;
  private owner: CalendarRequestTicket | null = null;

  begin(): CalendarRequestTicket | null {
    if (this.owner?.focusEpoch === this.focusEpoch) {
      return null;
    }

    const ticket = {
      focusEpoch: this.focusEpoch,
      requestId: ++this.nextRequestId,
    };
    this.owner = ticket;
    return ticket;
  }

  invalidateFocus(): void {
    this.focusEpoch += 1;
    this.owner = null;
  }

  isOwner(ticket: CalendarRequestTicket): boolean {
    return (
      ticket.focusEpoch === this.focusEpoch &&
      ticket.focusEpoch === this.owner?.focusEpoch &&
      ticket.requestId === this.owner.requestId
    );
  }

  finish(ticket: CalendarRequestTicket): boolean {
    if (!this.isOwner(ticket)) {
      return false;
    }
    this.owner = null;
    return true;
  }
}

export function formatDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function getMonthRange(year: number, monthIndex: number): CalendarDateRange {
  return {
    from: formatDate(new Date(year, monthIndex, 1)),
    to: formatDate(new Date(year, monthIndex + 1, 0)),
  };
}

export function getMonthRangeForDate(date: string): CalendarDateRange {
  const [year, month] = date.split('-').map(Number);
  return getMonthRange(year, month - 1);
}

export function getAdjacentMonthRange(range: CalendarDateRange, offset: -1 | 1): CalendarDateRange {
  const [year, month] = range.from.split('-').map(Number);
  return getMonthRange(year, month - 1 + offset);
}

export function listMonthDates(range: CalendarDateRange): string[] {
  const [year, month] = range.from.split('-').map(Number);
  const lastDay = Number(range.to.slice(-2));
  return Array.from({ length: lastDay }, (_, index) =>
    formatDate(new Date(year, month - 1, index + 1))
  );
}

export function sortPeriods(periods: CalendarPeriodData[]): CalendarPeriodData[] {
  return [...periods].sort(
    (left, right) => PERIOD_ORDER.indexOf(left.period) - PERIOD_ORDER.indexOf(right.period)
  );
}

export function sortPlanBlocks(planBlocks: CalendarPlanBlock[]): CalendarPlanBlock[] {
  return [...planBlocks].sort((left, right) => left.displayOrder - right.displayOrder);
}

export function sortFixedSchedules(schedules: CalendarFixedSchedule[]): CalendarFixedSchedule[] {
  return [...schedules].sort((left, right) =>
    left.segmentStartAt.localeCompare(right.segmentStartAt)
  );
}

export function getVisiblePlanBlocks(period: CalendarPeriodData): CalendarPlanBlock[] {
  const allowedStatuses =
    period.temporalState === 'PAST'
      ? new Set(['COMPLETED'])
      : period.temporalState === 'CURRENT'
        ? new Set(['PLANNED', 'CHECKED'])
        : new Set(['PLANNED']);

  return sortPlanBlocks(period.planBlocks.filter((block) => allowedStatuses.has(block.status)));
}

export function getVisibleCheckIn(period: CalendarPeriodData) {
  return period.temporalState === 'PAST' ? period.checkIn : null;
}

export function hasDayData(day: CalendarDay | undefined): boolean {
  return Boolean(
    day?.periods.some(
      (period) =>
        period.planBlocks.length > 0 ||
        period.fixedSchedules.length > 0 ||
        period.checkIn !== null
    )
  );
}

export function isDayEmpty(day: CalendarDay | undefined): boolean {
  return !hasDayData(day);
}

export function getCompletedCount(day: CalendarDay | undefined): number {
  return (
    day?.periods.reduce(
      (total, period) =>
        total +
        period.planBlocks.filter((block) => {
          if (period.temporalState === 'PAST') {
            return block.status === 'COMPLETED';
          }
          if (period.temporalState === 'CURRENT') {
            return block.status === 'CHECKED';
          }
          return false;
        }).length,
      0
    ) ?? 0
  );
}

export function hasOnlyFuturePeriods(day: CalendarDay | undefined): boolean {
  return Boolean(day && day.periods.length > 0 && day.periods.every((period) => period.temporalState === 'FUTURE'));
}

export function formatSegmentTime(value: string): string {
  const match = value.match(/T(\d{2}:\d{2})/);
  return match?.[1] ?? value;
}

export function isDateInRange(date: string, range: CalendarDateRange): boolean {
  return date >= range.from && date <= range.to;
}

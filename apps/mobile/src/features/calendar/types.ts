export type CalendarPeriod = 'MORNING' | 'AFTERNOON' | 'EVENING';
export type CalendarTemporalState = 'PAST' | 'CURRENT' | 'FUTURE';
export type CalendarPlanBlockStatus = 'PLANNED' | 'CHECKED' | 'COMPLETED' | 'NOT_DONE';

export type CalendarCheckIn = {
  id: string;
  score: number;
  totalPlanCount: number;
  completedPlanCount: number;
  finalizedAt: string;
};

export type CalendarPlanBlock = {
  id: string;
  displayTitle: string;
  status: CalendarPlanBlockStatus;
  displayOrder: number;
};

export type CalendarFixedSchedule = {
  id: string;
  title: string;
  startAt: string;
  endAt: string;
  segmentStartAt: string;
  segmentEndAt: string;
};

export type CalendarPeriodData = {
  period: CalendarPeriod;
  temporalState: CalendarTemporalState;
  checkIn: CalendarCheckIn | null;
  planBlocks: CalendarPlanBlock[];
  fixedSchedules: CalendarFixedSchedule[];
};

export type CalendarDay = {
  date: string;
  periods: CalendarPeriodData[];
};

export type CalendarResponse = {
  from: string;
  to: string;
  logicalToday: string;
  currentPeriod: CalendarPeriod;
  days: CalendarDay[];
};

export type CalendarDateRange = {
  from: string;
  to: string;
};

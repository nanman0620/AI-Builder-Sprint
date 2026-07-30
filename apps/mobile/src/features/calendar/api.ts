import { apiRequest } from '@/src/services/api/client';

import type { CalendarDateRange, CalendarResponse } from './types';

export function getCalendar({ from, to }: CalendarDateRange): Promise<CalendarResponse> {
  const query = new URLSearchParams({ from, to });
  return apiRequest<CalendarResponse>(`/calendar?${query.toString()}`);
}

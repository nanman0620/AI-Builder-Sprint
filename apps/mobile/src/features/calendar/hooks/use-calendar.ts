import { useFocusEffect } from '@react-navigation/native';
import { useCallback, useRef, useState } from 'react';

import { getCalendar } from '../api';
import {
  CalendarRequestOwnership,
  getAdjacentMonthRange,
  getMonthRange,
  getMonthRangeForDate,
  isDateInRange,
} from '../logic';
import type { CalendarRequestTicket } from '../logic';
import type { CalendarDateRange, CalendarResponse } from '../types';

function currentDeviceMonthRange(): CalendarDateRange {
  const now = new Date();
  return getMonthRange(now.getFullYear(), now.getMonth());
}

export function useCalendar() {
  const [data, setData] = useState<CalendarResponse | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [refreshError, setRefreshError] = useState(false);

  const dataRef = useRef<CalendarResponse | null>(null);
  const isActiveRef = useRef(false);
  const ownershipRef = useRef(new CalendarRequestOwnership());
  const inFlightRef = useRef<{ promise: Promise<void>; ticket: CalendarRequestTicket } | null>(null);
  const retryRangeRef = useRef<CalendarDateRange | null>(null);

  const loadRange = useCallback((requestedRange: CalendarDateRange, initial = false): Promise<void> => {
    const ownership = ownershipRef.current;
    const existing = inFlightRef.current;
    if (existing && ownership.isOwner(existing.ticket)) {
      return existing.promise;
    }

    const ticket = ownership.begin();
    if (!ticket) {
      return existing?.promise ?? Promise.resolve();
    }

    retryRangeRef.current = requestedRange;
    setIsLoading(true);

    const run = async () => {
      try {
        let result = await getCalendar(requestedRange);

        // 00:00~03:59의 logicalToday가 기기 달력 날짜와 다른 달이면, 서버가 정한 논리 날짜가
        // 포함된 월을 다시 받아 최초 선택 날짜와 표시 범위를 일치시킨다.
        if (initial && !isDateInRange(result.logicalToday, requestedRange)) {
          const logicalRange = getMonthRangeForDate(result.logicalToday);
          result = await getCalendar(logicalRange);
        }

        if (!isActiveRef.current || !ownership.isOwner(ticket)) {
          return;
        }

        dataRef.current = result;
        setData(result);
        setSelectedDate((previous) => {
          if (initial) {
            return result.logicalToday;
          }
          if (previous && isDateInRange(previous, result)) {
            return previous;
          }
          return isDateInRange(result.logicalToday, result) ? result.logicalToday : result.from;
        });
        setRefreshError(false);
        retryRangeRef.current = null;
      } catch {
        if (!isActiveRef.current || !ownership.isOwner(ticket)) {
          return;
        }
        setRefreshError(true);
      } finally {
        if (isActiveRef.current && ownership.isOwner(ticket)) {
          setIsLoading(false);
        }
      }
    };

    const promise = run().finally(() => {
      if (ownership.finish(ticket) && inFlightRef.current?.promise === promise) {
        inFlightRef.current = null;
      }
    });
    inFlightRef.current = { promise, ticket };
    return promise;
  }, []);

  useFocusEffect(
    useCallback(() => {
      isActiveRef.current = true;
      const current = dataRef.current;
      void loadRange(
        current ? { from: current.from, to: current.to } : currentDeviceMonthRange(),
        !current
      );

      return () => {
        isActiveRef.current = false;
        ownershipRef.current.invalidateFocus();
      };
    }, [loadRange])
  );

  const moveMonth = useCallback(
    (offset: -1 | 1) => {
      const current = dataRef.current;
      if (!current || (inFlightRef.current && ownershipRef.current.isOwner(inFlightRef.current.ticket))) {
        return;
      }
      void loadRange(getAdjacentMonthRange(current, offset));
    },
    [loadRange]
  );

  const retry = useCallback(() => {
    if (inFlightRef.current && ownershipRef.current.isOwner(inFlightRef.current.ticket)) {
      return;
    }
    const current = dataRef.current;
    const range = retryRangeRef.current ?? (current ? { from: current.from, to: current.to } : currentDeviceMonthRange());
    void loadRange(range, !current);
  }, [loadRange]);

  return {
    data,
    selectedDate,
    selectDate: setSelectedDate,
    isLoading,
    refreshError,
    moveMonth,
    retry,
  };
}

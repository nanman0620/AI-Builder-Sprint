import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import type { BootstrapResponse } from '../bootstrap/types';
import { useBootstrap } from '../bootstrap/bootstrap-context';
import { getSolarRequestExecution } from '../plan-management/api/solar-requests';
import type { ExecutionStatusResponse } from '../plan-management/types';
import {
  ExecutionTerminalTracker,
  getNextSeoulBoundary,
  getSeoulLogicalSnapshot,
  isSameSeoulLogicalSnapshot,
} from './logic';

const EXECUTION_POLL_INTERVAL_MS = 5000;
const MAX_TIMER_DELAY_MS = 2_147_000_000;

export type AppSyncDomain = 'home' | 'calendar' | 'planManagement' | 'profile';

type RefreshEpochs = Record<AppSyncDomain, number>;

type ExecutionEvent = {
  sequence: number;
  requestId: string;
  result: ExecutionStatusResponse | null;
  failedToRefresh: boolean;
};

type AppSyncContextValue = {
  epochs: RefreshEpochs;
  resetEpoch: number;
  isAppActive: boolean;
  executionEvent: ExecutionEvent | null;
  setAppActive: (active: boolean) => void;
  handleForegroundBootstrapSuccess: (bootstrap: BootstrapResponse) => void;
  watchExecution: (requestId: string | null) => void;
  refreshExecutionNow: (requestId: string) => Promise<void>;
  reset: () => void;
};

const initialEpochs: RefreshEpochs = {
  home: 0,
  calendar: 0,
  planManagement: 0,
  profile: 0,
};

const AppSyncContext = createContext<AppSyncContextValue | null>(null);

function getBootstrapExecutingRequestId(bootstrap: BootstrapResponse): string | null {
  if (bootstrap.planManagement?.screenMode !== 'EXECUTING') {
    return null;
  }
  const request = bootstrap.planManagement.request;
  return request && typeof request.id === 'string' ? request.id : null;
}

export function AppSyncProvider({ children }: { children: ReactNode }) {
  const { data: bootstrapData, status: bootstrapStatus } = useBootstrap();
  const [epochs, setEpochs] = useState<RefreshEpochs>(initialEpochs);
  const [resetEpoch, setResetEpoch] = useState(0);
  const [isAppActive, setIsAppActiveState] = useState(true);
  const [executionEvent, setExecutionEvent] = useState<ExecutionEvent | null>(null);

  const isMountedRef = useRef(true);
  const isAppActiveRef = useRef(true);
  const boundaryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const boundarySnapshotRef = useRef(getSeoulLogicalSnapshot(new Date()));
  const watchedRequestIdRef = useRef<string | null>(null);
  const executionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const executionInFlightRef = useRef<{
    requestId: string;
    generation: number;
    promise: Promise<void>;
  } | null>(null);
  const executionGenerationRef = useRef(0);
  const executionEventSequenceRef = useRef(0);
  const terminalTrackerRef = useRef(new ExecutionTerminalTracker());
  const pollExecutionRef = useRef<(requestId: string) => Promise<void>>(() => Promise.resolve());
  const scheduleBoundaryRef = useRef<() => void>(() => undefined);

  const invalidate = useCallback((domains: AppSyncDomain[]) => {
    if (!isMountedRef.current) {
      return;
    }
    setEpochs((previous) => {
      const next = { ...previous };
      for (const domain of domains) {
        next[domain] += 1;
      }
      return next;
    });
  }, []);

  const clearBoundaryTimer = useCallback(() => {
    if (boundaryTimerRef.current) {
      clearTimeout(boundaryTimerRef.current);
      boundaryTimerRef.current = null;
    }
  }, []);

  const clearExecutionTimer = useCallback(() => {
    if (executionTimerRef.current) {
      clearTimeout(executionTimerRef.current);
      executionTimerRef.current = null;
    }
  }, []);

  const scheduleExecutionPoll = useCallback(
    (requestId: string) => {
      clearExecutionTimer();
      if (!isAppActiveRef.current || watchedRequestIdRef.current !== requestId) {
        return;
      }
      executionTimerRef.current = setTimeout(() => {
        executionTimerRef.current = null;
        void pollExecutionRef.current(requestId);
      }, EXECUTION_POLL_INTERVAL_MS);
    },
    [clearExecutionTimer]
  );

  const pollExecution = useCallback(
    (requestId: string): Promise<void> => {
      const existing = executionInFlightRef.current;
      if (existing?.requestId === requestId) {
        return existing.promise;
      }
      if (!isAppActiveRef.current || watchedRequestIdRef.current !== requestId) {
        return Promise.resolve();
      }

      const generation = executionGenerationRef.current;
      const run = async () => {
        try {
          const result = await getSolarRequestExecution(requestId);
          if (
            !isMountedRef.current ||
            generation !== executionGenerationRef.current ||
            watchedRequestIdRef.current !== requestId
          ) {
            return;
          }

          setExecutionEvent({
            sequence: ++executionEventSequenceRef.current,
            requestId,
            result,
            failedToRefresh: false,
          });

          if (result.status === 'EXECUTING') {
            scheduleExecutionPoll(requestId);
            return;
          }

          clearExecutionTimer();
          watchedRequestIdRef.current = null;
          if (terminalTrackerRef.current.shouldHandle(requestId, result.status)) {
            invalidate(['home', 'calendar', 'planManagement']);
          }
        } catch {
          if (
            !isMountedRef.current ||
            generation !== executionGenerationRef.current ||
            watchedRequestIdRef.current !== requestId
          ) {
            return;
          }
          setExecutionEvent({
            sequence: ++executionEventSequenceRef.current,
            requestId,
            result: null,
            failedToRefresh: true,
          });
          scheduleExecutionPoll(requestId);
        }
      };

      const promise = run().finally(() => {
        if (
          executionInFlightRef.current?.requestId === requestId &&
          executionInFlightRef.current.generation === generation
        ) {
          executionInFlightRef.current = null;
        }
      });
      executionInFlightRef.current = { requestId, generation, promise };
      return promise;
    },
    [clearExecutionTimer, invalidate, scheduleExecutionPoll]
  );

  useEffect(() => {
    pollExecutionRef.current = pollExecution;
  }, [pollExecution]);

  const watchExecution = useCallback(
    (requestId: string | null) => {
      if (watchedRequestIdRef.current === requestId) {
        if (requestId && isAppActiveRef.current && !executionTimerRef.current) {
          void pollExecutionRef.current(requestId);
        }
        return;
      }

      executionGenerationRef.current += 1;
      executionInFlightRef.current = null;
      clearExecutionTimer();
      watchedRequestIdRef.current = requestId;
      terminalTrackerRef.current.reset();
      if (requestId && isAppActiveRef.current) {
        void pollExecutionRef.current(requestId);
      }
    },
    [clearExecutionTimer]
  );

  const refreshExecutionNow = useCallback(
    (requestId: string): Promise<void> => {
      if (watchedRequestIdRef.current !== requestId) {
        watchExecution(requestId);
      }
      return pollExecutionRef.current(requestId);
    },
    [watchExecution]
  );

  const scheduleBoundary = useCallback(() => {
    clearBoundaryTimer();
    if (!isAppActiveRef.current) {
      return;
    }

    const now = new Date();
    const nextBoundary = getNextSeoulBoundary(now);
    const delay = Math.min(
      Math.max(1, nextBoundary.getTime() - now.getTime()),
      MAX_TIMER_DELAY_MS
    );
    boundaryTimerRef.current = setTimeout(() => {
      boundaryTimerRef.current = null;
      const nextSnapshot = getSeoulLogicalSnapshot(new Date());
      if (!isSameSeoulLogicalSnapshot(boundarySnapshotRef.current, nextSnapshot)) {
        boundarySnapshotRef.current = nextSnapshot;
        invalidate(['home', 'calendar', 'planManagement']);
      }
      scheduleBoundaryRef.current();
    }, delay);
  }, [clearBoundaryTimer, invalidate]);

  useEffect(() => {
    scheduleBoundaryRef.current = scheduleBoundary;
  }, [scheduleBoundary]);

  const setAppActive = useCallback(
    (active: boolean) => {
      isAppActiveRef.current = active;
      setIsAppActiveState(active);
      if (!active) {
        clearBoundaryTimer();
        clearExecutionTimer();
        return;
      }
      scheduleBoundaryRef.current();
    },
    [clearBoundaryTimer, clearExecutionTimer]
  );

  const handleForegroundBootstrapSuccess = useCallback(
    (bootstrap: BootstrapResponse) => {
      const nextSnapshot = getSeoulLogicalSnapshot(new Date());
      boundarySnapshotRef.current = nextSnapshot;
      // foreground 동기화 자체가 네 도메인을 한 번 stale 처리하므로, 경계 통과도 이 증가에 통합된다.
      invalidate(['home', 'calendar', 'planManagement', 'profile']);
      watchExecution(getBootstrapExecutingRequestId(bootstrap));
      scheduleBoundaryRef.current();
    },
    [invalidate, watchExecution]
  );

  // 최초 실행·웹 direct route에서는 root AppState 복귀 경로를 거치지 않으므로,
  // bootstrap의 현재 EXECUTING 요청만 관찰해 공통 polling을 시작한다.
  useEffect(() => {
    if (bootstrapStatus === 'success' && bootstrapData) {
      watchExecution(getBootstrapExecutingRequestId(bootstrapData));
    }
  }, [bootstrapData, bootstrapStatus, watchExecution]);

  const reset = useCallback(() => {
    executionGenerationRef.current += 1;
    executionInFlightRef.current = null;
    watchedRequestIdRef.current = null;
    clearBoundaryTimer();
    clearExecutionTimer();
    terminalTrackerRef.current.reset();
    boundarySnapshotRef.current = getSeoulLogicalSnapshot(new Date());
    executionEventSequenceRef.current += 1;
    if (isMountedRef.current) {
      setResetEpoch((previous) => previous + 1);
      setExecutionEvent(null);
    }
  }, [clearBoundaryTimer, clearExecutionTimer]);

  useEffect(() => {
    isMountedRef.current = true;
    scheduleBoundaryRef.current();
    return () => {
      isMountedRef.current = false;
      clearBoundaryTimer();
      clearExecutionTimer();
      executionGenerationRef.current += 1;
    };
  }, [clearBoundaryTimer, clearExecutionTimer]);

  const value = useMemo<AppSyncContextValue>(
    () => ({
      epochs,
      resetEpoch,
      isAppActive,
      executionEvent,
      setAppActive,
      handleForegroundBootstrapSuccess,
      watchExecution,
      refreshExecutionNow,
      reset,
    }),
    [
      epochs,
      executionEvent,
      handleForegroundBootstrapSuccess,
      isAppActive,
      refreshExecutionNow,
      reset,
      resetEpoch,
      setAppActive,
      watchExecution,
    ]
  );

  return <AppSyncContext.Provider value={value}>{children}</AppSyncContext.Provider>;
}

export function useAppSync(): AppSyncContextValue {
  const context = useContext(AppSyncContext);
  if (!context) {
    throw new Error('useAppSync는 AppSyncProvider 내부에서만 사용할 수 있습니다.');
  }
  return context;
}

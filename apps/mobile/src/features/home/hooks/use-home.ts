import { useFocusEffect } from '@react-navigation/native';
import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiClientError } from '@/src/services/api/client';

import { getHomeCurrent, patchPlanBlockCheckState, postCheckInAcknowledge, postDeadlineWarningsAcknowledge } from '../api';
import { applyOptimisticCheckState, computeOptimisticProgress } from '../logic';
import type { DeadlineWarningItem, HomeCurrentResponse } from '../types';

// 문구는 docs/ai/IMPLEMENTATION_CONTEXT.md 11절 "일반 오류" 표준 문구.
const GENERIC_ERROR_MESSAGE = '정보를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.';

// FINALIZING 폴링 주기. API 명세가 정한 값이 아니라 프론트 구현 선택값이라 상수로 분리해 둔다(§7).
export const FINALIZING_POLL_INTERVAL_MS = 5000;

// 이미 다른 분기로 넘어갔거나 정산이 끝나 현재 체크 요청이 더 이상 유효하지 않음을 뜻하는 코드.
// docs/ai/IMPLEMENTATION_CONTEXT.md 11절: PERIOD_ALREADY_FINALIZED → 홈 재조회. 그 외 체크 오류
// (PLAN_BLOCK_NOT_FOUND/BLOCK_NOT_IN_CURRENT_PERIOD/INVALID_CHECK_STATE)는 체크 원상 복구만 한다.
const CHECK_STATE_REQUIRES_RELOAD_CODES = new Set([
  'PERIOD_ALREADY_FINALIZED',
  'BLOCK_NOT_IN_CURRENT_PERIOD',
]);

export function useHome() {
  const [data, setData] = useState<HomeCurrentResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [hasLoadError, setHasLoadError] = useState(false);
  const [finalizingRefreshError, setFinalizingRefreshError] = useState(false);

  const [isCheckPending, setIsCheckPending] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);

  const [isDeadlineAckPending, setIsDeadlineAckPending] = useState(false);
  const [deadlineAckError, setDeadlineAckError] = useState<string | null>(null);

  const [isCheckInAckPending, setIsCheckInAckPending] = useState(false);
  const [checkInAckError, setCheckInAckError] = useState<string | null>(null);

  // React state 반영 전 같은 이벤트 루프에서 연속 입력되는 경우까지 막기 위한 동기 in-flight guard.
  const checkPendingRef = useRef(false);
  const deadlineAckPendingRef = useRef(false);
  const checkInAckPendingRef = useRef(false);

  // 홈 탭이 포커스 상태일 때만 true. 조회 결과가 늦게 도착했을 때 blur·unmount 이후 상태 갱신을 막는 데 쓴다.
  const isActiveRef = useRef(false);
  // 최신 data를 stale closure 없이 읽기 위한 ref(loadHome을 deps 없는 안정적인 콜백으로 유지하기 위함).
  const dataRef = useRef<HomeCurrentResponse | null>(null);
  useEffect(() => {
    dataRef.current = data;
  }, [data]);

  // 진행 중인 GET /home/current 하나를 공유해 중복 요청을 막는다(bootstrap-context.tsx와 동일한 패턴).
  const inFlightRef = useRef<Promise<void> | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // schedulePoll이 loadHome을 참조할 때 useCallback 순환 의존을 피하기 위한 최신 함수 포인터.
  const loadHomeRef = useRef<() => Promise<void>>(() => Promise.resolve());

  const clearPollTimer = useCallback(() => {
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const schedulePoll = useCallback(() => {
    clearPollTimer();
    pollTimerRef.current = setTimeout(() => {
      pollTimerRef.current = null;
      if (!isActiveRef.current) {
        return;
      }
      loadHomeRef.current();
    }, FINALIZING_POLL_INTERVAL_MS);
  }, [clearPollTimer]);

  // 홈 탭 포커스 시 GET /home/current(§1), FINALIZING 동안의 재조회(§7)가 모두 이 함수 하나를 공유한다.
  // 조회 중에는 새 호출이 들어와도 새 요청을 만들지 않고 진행 중인 Promise를 그대로 반환한다.
  const loadHome = useCallback((): Promise<void> => {
    if (inFlightRef.current) {
      return inFlightRef.current;
    }

    setIsLoading(true);

    const run = async () => {
      try {
        const result = await getHomeCurrent();
        if (!isActiveRef.current) {
          return;
        }
        setData(result);
        setHasLoadError(false);
        setFinalizingRefreshError(false);
        if (result.homeMode === 'FINALIZING') {
          schedulePoll();
        } else {
          clearPollTimer();
        }
      } catch {
        if (!isActiveRef.current) {
          return;
        }
        // FINALIZING 조회 실패는 정산 실패가 아니다(§7). 기존 화면을 유지하고 폴링도 계속 이어간다.
        if (dataRef.current?.homeMode === 'FINALIZING') {
          setFinalizingRefreshError(true);
          schedulePoll();
        } else if (!dataRef.current) {
          setHasLoadError(true);
        }
        // 그 외(FINALIZING이 아닌 상태에서의 백그라운드 재조회 실패)는 마지막으로 확인된 화면을 그대로 유지한다.
      } finally {
        if (isActiveRef.current) {
          setIsLoading(false);
        }
        inFlightRef.current = null;
      }
    };

    const promise = run();
    inFlightRef.current = promise;
    return promise;
  }, [clearPollTimer, schedulePoll]);

  useEffect(() => {
    loadHomeRef.current = loadHome;
  }, [loadHome]);

  useFocusEffect(
    useCallback(() => {
      isActiveRef.current = true;
      loadHome();
      return () => {
        isActiveRef.current = false;
        clearPollTimer();
      };
    }, [loadHome, clearPollTimer])
  );

  // PlanBlock 체크/해제. MVP에서는 한 번에 하나의 체크 요청만 허용한다(§6).
  const toggleCheckState = useCallback(
    async (planBlockId: string, nextChecked: boolean) => {
      if (checkPendingRef.current || !dataRef.current) {
        return;
      }
      checkPendingRef.current = true;

      const previousPlanBlocks = dataRef.current.planBlocks;
      const previousProgress = dataRef.current.progress;
      const optimisticPlanBlocks = applyOptimisticCheckState(
        previousPlanBlocks,
        planBlockId,
        nextChecked,
        new Date().toISOString()
      );
      const optimisticProgress = computeOptimisticProgress(optimisticPlanBlocks);

      setData((prev) => (prev ? { ...prev, planBlocks: optimisticPlanBlocks, progress: optimisticProgress } : prev));
      setCheckError(null);
      setIsCheckPending(true);

      try {
        const result = await patchPlanBlockCheckState(planBlockId, nextChecked);
        if (!isActiveRef.current) {
          return;
        }
        setData((prev) =>
          prev
            ? {
                ...prev,
                planBlocks: prev.planBlocks.map((block) =>
                  block.id === result.planBlock.id ? result.planBlock : block
                ),
                progress: result.progress,
              }
            : prev
        );
      } catch (error) {
        if (!isActiveRef.current) {
          return;
        }
        // 실패 시 기존 planBlocks·progress로 복구한다(체크 원상 복구, §6).
        setData((prev) => (prev ? { ...prev, planBlocks: previousPlanBlocks, progress: previousProgress } : prev));

        if (error instanceof ApiClientError && CHECK_STATE_REQUIRES_RELOAD_CODES.has(error.code)) {
          await loadHome();
          return;
        }
        setCheckError(error instanceof ApiClientError ? error.message : GENERIC_ERROR_MESSAGE);
      } finally {
        checkPendingRef.current = false;
        setIsCheckPending(false);
      }
    },
    [loadHome]
  );

  // 마감 경고 일괄 확인. 성공 후에는 반드시 GET /home/current를 다시 호출하고, 다음 homeMode를
  // 로컬에서 추측하지 않는다(§4, §8). 실패하면 현재 경고 화면과 목록을 그대로 유지한다.
  const acknowledgeDeadlineWarnings = useCallback(
    async (items: DeadlineWarningItem[]) => {
      if (deadlineAckPendingRef.current || items.length === 0) {
        return;
      }
      deadlineAckPendingRef.current = true;
      const taskIds = items.map((item) => item.taskId);
      setDeadlineAckError(null);
      setIsDeadlineAckPending(true);
      try {
        await postDeadlineWarningsAcknowledge(taskIds);
        if (!isActiveRef.current) {
          return;
        }
        await loadHome();
      } catch (error) {
        if (!isActiveRef.current) {
          return;
        }
        setDeadlineAckError(error instanceof ApiClientError ? error.message : GENERIC_ERROR_MESSAGE);
      } finally {
        deadlineAckPendingRef.current = false;
        setIsDeadlineAckPending(false);
      }
    },
    [loadHome]
  );

  // CheckIn 결과 확인. 성공 후 GET /home/current 재조회로 다음 homeMode를 서버 판정 그대로 받는다(§4, §9).
  const acknowledgeCheckIn = useCallback(
    async (checkInId: string) => {
      if (checkInAckPendingRef.current) {
        return;
      }
      checkInAckPendingRef.current = true;
      setCheckInAckError(null);
      setIsCheckInAckPending(true);
      try {
        await postCheckInAcknowledge(checkInId);
        if (!isActiveRef.current) {
          return;
        }
        await loadHome();
      } catch (error) {
        if (!isActiveRef.current) {
          return;
        }
        setCheckInAckError(error instanceof ApiClientError ? error.message : GENERIC_ERROR_MESSAGE);
      } finally {
        checkInAckPendingRef.current = false;
        setIsCheckInAckPending(false);
      }
    },
    [loadHome]
  );

  return {
    data,
    isLoading,
    hasLoadError,
    finalizingRefreshError,
    reload: loadHome,
    isCheckPending,
    checkError,
    toggleCheckState,
    isDeadlineAckPending,
    deadlineAckError,
    acknowledgeDeadlineWarnings,
    isCheckInAckPending,
    checkInAckError,
    acknowledgeCheckIn,
  };
}

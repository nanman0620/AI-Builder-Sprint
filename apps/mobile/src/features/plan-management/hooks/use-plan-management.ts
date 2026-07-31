import { useFocusEffect } from '@react-navigation/native';
import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiClientError } from '@/src/services/api/client';

import { getPlanManagementState } from '../api/plan-management-state';
import {
  acknowledgeSolarRequestResult,
  createSolarRequest,
  deleteSolarRequest,
  executeSolarRequest,
  getSolarRequestExecution,
  reopenSolarRequest,
  retrySolarRequest,
  sendSolarMessage,
  submitSolarDecision,
} from '../api/solar-requests';
import type {
  DecisionOption,
  ExecutionStartResponse,
  ExecutionStatusResponse,
  PlanManagementState,
  RequestPurpose,
} from '../types';
import { generateClientEventId } from '../utils/client-event-id';

const GENERIC_ACTION_ERROR_MESSAGE = '정보를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.';
const EXECUTION_REFRESH_ERROR_MESSAGE =
  '진행 상태를 확인하지 못했어요.\n작업은 계속 진행 중일 수 있어요.';

// 최종 API는 polling 간격을 반환하지 않는다. 저장소의 기존 FINALIZING polling 정책과
// 같은 5초를 사용해 일시적 오류 때 과도한 재호출을 피한다.
export const EXECUTION_POLL_INTERVAL_MS = 5000;

const EXECUTION_STATE_ERROR_CODES = new Set([
  'INVALID_REQUEST_STATE',
  'REQUEST_ALREADY_EXECUTING',
]);

export function usePlanManagement() {
  const [state, setState] = useState<PlanManagementState | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [hasLoadError, setHasLoadError] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [exitError, setExitError] = useState<string | null>(null);
  const [executionRefreshError, setExecutionRefreshError] = useState<string | null>(null);
  const [isExecutionRefreshing, setIsExecutionRefreshing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const pendingActionRef = useRef<string | null>(null);
  const stateRef = useRef<PlanManagementState | null>(null);
  const isActiveRef = useRef(false);
  const executionInFlightRef = useRef<{
    requestId: string;
    promise: Promise<void>;
  } | null>(null);
  const executionPollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const deletedFailedRequestIdRef = useRef<string | null>(null);
  const refreshExecutionRef = useRef<(requestId: string) => Promise<void>>(() =>
    Promise.resolve()
  );

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const beginAction = useCallback((key: string) => {
    if (pendingActionRef.current) {
      return false;
    }
    pendingActionRef.current = key;
    setIsSubmitting(true);
    return true;
  }, []);

  const finishAction = useCallback((key: string) => {
    if (pendingActionRef.current === key) {
      pendingActionRef.current = null;
      setIsSubmitting(false);
    }
  }, []);

  const clearExecutionPollTimer = useCallback(() => {
    if (executionPollTimerRef.current) {
      clearTimeout(executionPollTimerRef.current);
      executionPollTimerRef.current = null;
    }
  }, []);

  const scheduleExecutionPoll = useCallback(
    (requestId: string) => {
      clearExecutionPollTimer();
      if (!isActiveRef.current) {
        return;
      }
      executionPollTimerRef.current = setTimeout(() => {
        executionPollTimerRef.current = null;
        const current = stateRef.current;
        if (
          !isActiveRef.current ||
          current?.screenMode !== 'EXECUTING' ||
          current.request?.id !== requestId
        ) {
          return;
        }
        void refreshExecutionRef.current(requestId);
      }, EXECUTION_POLL_INTERVAL_MS);
    },
    [clearExecutionPollTimer]
  );

  const applyExecutionResponse = useCallback((result: ExecutionStatusResponse) => {
    setState((previous) => {
      if (!previous?.request || previous.request.id !== result.requestId) {
        return previous;
      }
      return {
        ...previous,
        screenMode: result.screenMode,
        request: {
          ...previous.request,
          status: result.status,
          execution: {
            executionStartedAt: result.executionStartedAt,
            executionAttemptCount: result.executionAttemptCount,
            executedAt: result.executedAt,
            executionResult: result.executionResult,
            error: result.error,
          },
        },
      } as PlanManagementState;
    });
  }, []);

  const refreshExecution = useCallback(
    (requestId: string): Promise<void> => {
      const existingRequest = executionInFlightRef.current;
      if (existingRequest?.requestId === requestId) {
        return existingRequest.promise;
      }

      setIsExecutionRefreshing(true);
      const run = async () => {
        try {
          const result = await getSolarRequestExecution(requestId);
          if (!isActiveRef.current) {
            return;
          }
          setExecutionRefreshError(null);
          applyExecutionResponse(result);
          if (result.status === 'EXECUTING') {
            scheduleExecutionPoll(requestId);
          } else {
            clearExecutionPollTimer();
          }
        } catch (error) {
          if (!isActiveRef.current) {
            return;
          }
          // HTTP/API 조회 오류와 data.error(실제 FAILED)는 서로 다른 경로다. 이 catch는
          // 기존 EXECUTING 화면을 유지하며 서버 작업 실패로 매핑하지 않는다.
          setExecutionRefreshError(
            error instanceof ApiClientError && error.code === 'REQUEST_NOT_FOUND'
              ? error.message
              : EXECUTION_REFRESH_ERROR_MESSAGE
          );
          const current = stateRef.current;
          if (
            current?.screenMode === 'EXECUTING' &&
            current.request?.id === requestId
          ) {
            scheduleExecutionPoll(requestId);
          }
        }
      };

      const promise = run().finally(() => {
        if (executionInFlightRef.current?.promise === promise) {
          executionInFlightRef.current = null;
          if (isActiveRef.current) {
            setIsExecutionRefreshing(false);
          }
        }
      });
      executionInFlightRef.current = { requestId, promise };
      return promise;
    },
    [applyExecutionResponse, clearExecutionPollTimer, scheduleExecutionPoll]
  );

  useEffect(() => {
    refreshExecutionRef.current = refreshExecution;
  }, [refreshExecution]);

  // GET /plan-management/state 하나로 screenMode와 request 전체(messages/requestItems/...)를
  // 함께 받으므로, 상태 복원을 위해 GET /solar/requests/{id}를 추가로 호출하지 않는다.
  const load = useCallback(async (): Promise<PlanManagementState | null> => {
    setIsLoading(true);
    setHasLoadError(false);
    try {
      const result = await getPlanManagementState();
      setState(result);
      return result;
    } catch {
      setHasLoadError(true);
      return null;
    } finally {
      setIsLoading(false);
    }
  }, []);

  const reloadAfterInvalidState = useCallback(async () => {
    try {
      const result = await getPlanManagementState();
      setState(result);
    } catch {
      // 재조회도 실패하면 마지막으로 확인한 화면과 요청을 유지한다.
      setActionError(GENERIC_ACTION_ERROR_MESSAGE);
    }
  }, []);

  // 탭 포커스마다 최신 screenMode를 복원한다. 실행 관련 모드라면 같은 requestId의
  // execution GET으로 상세 결과를 확인하고, EXECUTING일 때만 polling을 이어간다.
  useFocusEffect(
    useCallback(() => {
      isActiveRef.current = true;
      void load().then((result) => {
        const executionState = result ?? stateRef.current;
        if (
          executionState?.request &&
          (executionState.screenMode === 'EXECUTING' ||
            executionState.screenMode === 'EXECUTION_SUCCESS' ||
            executionState.screenMode === 'EXECUTION_FAILED')
        ) {
          void refreshExecutionRef.current(executionState.request.id);
        }
      });
      return () => {
        isActiveRef.current = false;
        clearExecutionPollTimer();
      };
    }, [clearExecutionPollTimer, load])
  );

  const executionRequestId = state?.request?.id ?? null;
  const shouldPollExecution = state?.screenMode === 'EXECUTING' && !!executionRequestId;

  useEffect(() => {
    clearExecutionPollTimer();
    if (isActiveRef.current && shouldPollExecution && executionRequestId) {
      scheduleExecutionPoll(executionRequestId);
    }
  }, [
    clearExecutionPollTimer,
    executionRequestId,
    scheduleExecutionPoll,
    shouldPollExecution,
  ]);

  const submitInitialMessage = useCallback(
    async (purpose: RequestPurpose, message: string) => {
      const actionKey = `create:${purpose}`;
      if (!beginAction(actionKey)) return;
      setActionError(null);
      try {
        const result = await createSolarRequest({
          purpose,
          clientEventId: generateClientEventId(),
          message,
        });
        setState(result);
      } catch (error) {
        if (error instanceof ApiClientError && error.code === 'ACTIVE_REQUEST_EXISTS') {
          // 이미 진행 중인 요청이 있으면 새로 만들지 않고 GET /plan-management/state로
          // 기존 요청을 그대로 복원한다.
          await load();
          return;
        }
        // 네트워크 오류를 포함해 어떤 실패든 기존 state는 건드리지 않고 오류만 보여준다.
        setActionError(error instanceof ApiClientError ? error.message : GENERIC_ACTION_ERROR_MESSAGE);
      } finally {
        finishAction(actionKey);
      }
    },
    [beginAction, finishAction, load]
  );

  const sendAnswer = useCallback(
    async (message: string) => {
      if (!state || !state.request) return;
      const requestId = state.request.id;
      const actionKey = `${requestId}:message`;
      if (!beginAction(actionKey)) return;
      setActionError(null);
      try {
        const result = await sendSolarMessage(requestId, {
          clientEventId: generateClientEventId(),
          message,
        });
        setState(result);
      } catch (error) {
        if (error instanceof ApiClientError && error.code === 'INVALID_REQUEST_STATE') {
          await reloadAfterInvalidState();
          return;
        }
        // 오류가 나면 화면과 기존 요청 데이터를 그대로 유지하고 오류만 보여준다.
        setActionError(error instanceof ApiClientError ? error.message : GENERIC_ACTION_ERROR_MESSAGE);
      } finally {
        finishAction(actionKey);
      }
    },
    [beginAction, finishAction, reloadAfterInvalidState, state]
  );

  const submitDecision = useCallback(
    async (decision: DecisionOption['value']) => {
      if (!state?.request) return;
      const requestId = state.request.id;
      const actionKey = `${requestId}:decision`;
      if (!beginAction(actionKey)) return;
      setActionError(null);
      try {
        const result = await submitSolarDecision(requestId, {
          clientEventId: generateClientEventId(),
          decision,
        });
        setState(result);
      } catch (error) {
        if (error instanceof ApiClientError && error.code === 'INVALID_REQUEST_STATE') {
          await reloadAfterInvalidState();
          return;
        }
        setActionError(error instanceof ApiClientError ? error.message : GENERIC_ACTION_ERROR_MESSAGE);
      } finally {
        finishAction(actionKey);
      }
    },
    [beginAction, finishAction, reloadAfterInvalidState, state]
  );

  const reopenRequest = useCallback(async () => {
    if (!state?.request) return;
    const requestId = state.request.id;
    const actionKey = `${requestId}:reopen`;
    if (!beginAction(actionKey)) return;
    setActionError(null);
    try {
      const result = await reopenSolarRequest(requestId);
      setState(result);
    } catch (error) {
      if (error instanceof ApiClientError && error.code === 'INVALID_REQUEST_STATE') {
        await reloadAfterInvalidState();
        return;
      }
      setActionError(error instanceof ApiClientError ? error.message : GENERIC_ACTION_ERROR_MESSAGE);
    } finally {
      finishAction(actionKey);
    }
  }, [beginAction, finishAction, reloadAfterInvalidState, state]);

  const setExecutingState = useCallback((result: ExecutionStartResponse) => {
    setExecutionRefreshError(null);
    setState((previous) => {
      if (!previous?.request || previous.request.id !== result.requestId) {
        return previous;
      }
      return {
        ...previous,
        screenMode: 'EXECUTING',
        request: {
          ...previous.request,
          status: 'EXECUTING',
          execution: null,
        },
      };
    });
  }, []);

  const executeRequest = useCallback(async () => {
    if (!state?.request || state.screenMode !== 'FINAL_REVIEW') return;
    const requestId = state.request.id;
    const actionKey = `${requestId}:execute`;
    if (!beginAction(actionKey)) return;
    setActionError(null);
    try {
      const result = await executeSolarRequest(requestId);
      setExecutingState(result);
      void refreshExecution(requestId);
    } catch (error) {
      if (
        error instanceof ApiClientError &&
        EXECUTION_STATE_ERROR_CODES.has(error.code)
      ) {
        if (error.code === 'REQUEST_ALREADY_EXECUTING') {
          await refreshExecution(requestId);
        } else {
          await reloadAfterInvalidState();
        }
        return;
      }
      // execute 전송/API 실패는 FINAL_REVIEW와 기존 검토 카드를 그대로 유지한다.
      setActionError(
        error instanceof ApiClientError ? error.message : GENERIC_ACTION_ERROR_MESSAGE
      );
    } finally {
      finishAction(actionKey);
    }
  }, [
    beginAction,
    finishAction,
    refreshExecution,
    reloadAfterInvalidState,
    setExecutingState,
    state,
  ]);

  const retryExecution = useCallback(async () => {
    if (!state?.request || state.screenMode !== 'EXECUTION_FAILED') return;
    const requestId = state.request.id;
    const actionKey = `${requestId}:retry`;
    if (!beginAction(actionKey)) return;
    setActionError(null);
    try {
      const result = await retrySolarRequest(requestId);
      setExecutingState(result);
      void refreshExecution(requestId);
    } catch (error) {
      if (
        error instanceof ApiClientError &&
        EXECUTION_STATE_ERROR_CODES.has(error.code)
      ) {
        if (error.code === 'REQUEST_ALREADY_EXECUTING') {
          await refreshExecution(requestId);
        } else {
          await reloadAfterInvalidState();
        }
        return;
      }
      // retry 호출 실패는 서버의 기존 FAILED 결과와 카드를 덮어쓰지 않는다.
      setActionError(
        error instanceof ApiClientError ? error.message : GENERIC_ACTION_ERROR_MESSAGE
      );
    } finally {
      finishAction(actionKey);
    }
  }, [
    beginAction,
    finishAction,
    refreshExecution,
    reloadAfterInvalidState,
    setExecutingState,
    state,
  ]);

  const acknowledgeExecutionResult = useCallback(async () => {
    if (!state?.request || state.screenMode !== 'EXECUTION_SUCCESS') return false;
    const requestId = state.request.id;
    const actionKey = `${requestId}:acknowledge-result`;
    if (!beginAction(actionKey)) return false;
    setActionError(null);
    try {
      await acknowledgeSolarRequestResult(requestId);
      return true;
    } catch (error) {
      if (error instanceof ApiClientError && error.code === 'INVALID_REQUEST_STATE') {
        await reloadAfterInvalidState();
        return false;
      }
      setActionError(
        error instanceof ApiClientError ? error.message : GENERIC_ACTION_ERROR_MESSAGE
      );
      return false;
    } finally {
      finishAction(actionKey);
    }
  }, [beginAction, finishAction, reloadAfterInvalidState, state]);

  const cancelFailedRequest = useCallback(async () => {
    if (!state?.request || state.screenMode !== 'EXECUTION_FAILED') return;
    const requestId = state.request.id;
    const actionKey = `${requestId}:cancel-failed`;
    if (!beginAction(actionKey)) return;
    setActionError(null);
    try {
      if (deletedFailedRequestIdRef.current !== requestId) {
        await deleteSolarRequest(requestId);
        deletedFailedRequestIdRef.current = requestId;
      }
      const result = await getPlanManagementState();
      setState(result);
      deletedFailedRequestIdRef.current = null;
    } catch (error) {
      if (error instanceof ApiClientError && error.code === 'INVALID_REQUEST_STATE') {
        await reloadAfterInvalidState();
        return;
      }
      setActionError(
        error instanceof ApiClientError ? error.message : GENERIC_ACTION_ERROR_MESSAGE
      );
    } finally {
      finishAction(actionKey);
    }
  }, [beginAction, finishAction, reloadAfterInvalidState, state]);

  const deleteCurrentRequest = useCallback(async () => {
    if (!state?.request) return false;
    const requestId = state.request.id;
    const actionKey = `${requestId}:delete`;
    if (!beginAction(actionKey)) return false;
    setExitError(null);
    try {
      await deleteSolarRequest(requestId);
      setState(null);
      return true;
    } catch (error) {
      if (error instanceof ApiClientError && error.code === 'INVALID_REQUEST_STATE') {
        await reloadAfterInvalidState();
      }
      setExitError(error instanceof ApiClientError ? error.message : GENERIC_ACTION_ERROR_MESSAGE);
      return false;
    } finally {
      finishAction(actionKey);
    }
  }, [beginAction, finishAction, reloadAfterInvalidState, state]);

  return {
    state,
    isLoading,
    hasLoadError,
    actionError,
    exitError,
    executionRefreshError,
    isExecutionRefreshing,
    isSubmitting,
    reload: load,
    submitInitialMessage,
    sendAnswer,
    submitDecision,
    reopenRequest,
    executeRequest,
    refreshExecution,
    retryExecution,
    acknowledgeExecutionResult,
    cancelFailedRequest,
    deleteCurrentRequest,
    clearActionError: () => setActionError(null),
    clearExitError: () => setExitError(null),
  };
}

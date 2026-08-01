import { useFocusEffect } from '@react-navigation/native';
import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiClientError } from '@/src/services/api/client';
import { useAppSync } from '@/src/features/app-sync/app-sync-context';

import { getPlanManagementState } from '../api/plan-management-state';
import {
  acknowledgeSolarRequestResult,
  createSolarRequest,
  deleteSolarRequest,
  executeSolarRequest,
  reopenSolarRequest,
  retrySolarRequest,
  sendSolarMessage,
  submitSolarDecision,
} from '../api/solar-requests';
import { applyAcknowledgeResult } from '../logic';
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

const EXECUTION_STATE_ERROR_CODES = new Set([
  'INVALID_REQUEST_STATE',
  'REQUEST_ALREADY_EXECUTING',
]);

export function usePlanManagement() {
  const {
    epochs,
    executionEvent,
    refreshExecutionNow,
    resetEpoch,
    watchExecution,
  } = useAppSync();
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
  const isMountedRef = useRef(true);
  const stateInFlightRef = useRef<Promise<PlanManagementState | null> | null>(null);
  const stateRequestIdRef = useRef(0);
  const seenRefreshEpochRef = useRef(epochs.planManagement);
  const seenExecutionEventRef = useRef(0);
  const seenResetEpochRef = useRef(resetEpoch);
  const deletedFailedRequestIdRef = useRef<string | null>(null);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    if (state?.screenMode === 'EXECUTING' && state.request) {
      watchExecution(state.request.id);
    } else if (state) {
      watchExecution(null);
    }
  }, [state, watchExecution]);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      stateRequestIdRef.current += 1;
    };
  }, []);

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

  const applyMutationState = useCallback((result: PlanManagementState) => {
    stateRequestIdRef.current += 1;
    stateInFlightRef.current = null;
    setState(result);
  }, []);

  const applyExecutionResponse = useCallback((result: ExecutionStatusResponse) => {
    stateRequestIdRef.current += 1;
    stateInFlightRef.current = null;
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
    async (requestId: string): Promise<void> => {
      setIsExecutionRefreshing(true);
      try {
        await refreshExecutionNow(requestId);
      } finally {
        if (isMountedRef.current) {
          setIsExecutionRefreshing(false);
        }
      }
    },
    [refreshExecutionNow]
  );

  // GET /plan-management/state 하나로 screenMode와 request 전체(messages/requestItems/...)를
  // 함께 받으므로, 상태 복원을 위해 GET /solar/requests/{id}를 추가로 호출하지 않는다.
  const load = useCallback((): Promise<PlanManagementState | null> => {
    if (stateInFlightRef.current) {
      return stateInFlightRef.current;
    }
    const requestId = ++stateRequestIdRef.current;
    setIsLoading(true);
    setHasLoadError(false);
    const run = async () => {
      try {
        const result = await getPlanManagementState();
        if (!isMountedRef.current || requestId !== stateRequestIdRef.current) {
          return null;
        }
        setState(result);
        if (result.screenMode === 'EXECUTING' && result.request) {
          watchExecution(result.request.id);
        }
        return result;
      } catch {
        if (isMountedRef.current && requestId === stateRequestIdRef.current) {
          setHasLoadError(true);
        }
        return null;
      } finally {
        if (isMountedRef.current && requestId === stateRequestIdRef.current) {
          setIsLoading(false);
        }
      }
    };
    const promise = run().finally(() => {
      if (stateInFlightRef.current === promise) {
        stateInFlightRef.current = null;
      }
    });
    stateInFlightRef.current = promise;
    return promise;
  }, [watchExecution]);

  const reloadAfterInvalidState = useCallback(async () => {
    const result = await load();
    if (!result) {
      // 재조회도 실패하면 마지막으로 확인한 화면과 요청을 유지한다.
      setActionError(GENERIC_ACTION_ERROR_MESSAGE);
    }
  }, [load]);

  // 탭 포커스마다 최신 screenMode를 복원한다. EXECUTING 감시는 AppSyncProvider가
  // 앱 공통 영역에서 소유하므로 blur 시 중단하지 않는다.
  useFocusEffect(
    useCallback(() => {
      isActiveRef.current = true;
      void load();
      return () => {
        isActiveRef.current = false;
      };
    }, [load])
  );

  useEffect(() => {
    if (seenRefreshEpochRef.current === epochs.planManagement) {
      return;
    }
    seenRefreshEpochRef.current = epochs.planManagement;
    if (isActiveRef.current) {
      void load();
    }
  }, [epochs.planManagement, load]);

  useEffect(() => {
    if (!executionEvent || seenExecutionEventRef.current === executionEvent.sequence) {
      return;
    }
    seenExecutionEventRef.current = executionEvent.sequence;
    const current = stateRef.current;
    if (!current?.request || current.request.id !== executionEvent.requestId) {
      return;
    }
    if (executionEvent.failedToRefresh) {
      if (current.screenMode === 'EXECUTING') {
        setExecutionRefreshError(EXECUTION_REFRESH_ERROR_MESSAGE);
      }
      return;
    }
    if (executionEvent.result) {
      setExecutionRefreshError(null);
      applyExecutionResponse(executionEvent.result);
    }
  }, [applyExecutionResponse, executionEvent]);

  useEffect(() => {
    if (seenResetEpochRef.current === resetEpoch) {
      return;
    }
    seenResetEpochRef.current = resetEpoch;
    isActiveRef.current = false;
    stateRequestIdRef.current += 1;
    stateInFlightRef.current = null;
    stateRef.current = null;
    setState(null);
    setIsLoading(true);
    setHasLoadError(false);
    setActionError(null);
    setExitError(null);
    setExecutionRefreshError(null);
    setIsExecutionRefreshing(false);
    pendingActionRef.current = null;
    setIsSubmitting(false);
  }, [resetEpoch]);

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
        applyMutationState(result);
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
    [applyMutationState, beginAction, finishAction, load]
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
        applyMutationState(result);
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
    [applyMutationState, beginAction, finishAction, reloadAfterInvalidState, state]
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
        applyMutationState(result);
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
    [applyMutationState, beginAction, finishAction, reloadAfterInvalidState, state]
  );

  const reopenRequest = useCallback(async () => {
    if (!state?.request) return;
    const requestId = state.request.id;
    const actionKey = `${requestId}:reopen`;
    if (!beginAction(actionKey)) return;
    setActionError(null);
    try {
      const result = await reopenSolarRequest(requestId);
      applyMutationState(result);
    } catch (error) {
      if (error instanceof ApiClientError && error.code === 'INVALID_REQUEST_STATE') {
        await reloadAfterInvalidState();
        return;
      }
      setActionError(error instanceof ApiClientError ? error.message : GENERIC_ACTION_ERROR_MESSAGE);
    } finally {
      finishAction(actionKey);
    }
  }, [applyMutationState, beginAction, finishAction, reloadAfterInvalidState, state]);

  const setExecutingState = useCallback((result: ExecutionStartResponse) => {
    setExecutionRefreshError(null);
    stateRequestIdRef.current += 1;
    stateInFlightRef.current = null;
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
      const result = await acknowledgeSolarRequestResult(requestId);
      // 서버가 이미 result_acknowledged_at을 저장했으므로, 다음 탭 재포커스(GET
      // /plan-management/state)를 기다리지 않고 로컬 상태를 곧바로 다음 화면으로 전환한다.
      // 그렇지 않으면 탭이 마운트된 채로 남아 있는 동안 EXECUTION_SUCCESS가 그대로 보일 수 있다.
      stateRequestIdRef.current += 1;
      stateInFlightRef.current = null;
      setState((previous) => (previous ? applyAcknowledgeResult(previous, result) : previous));
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
      applyMutationState(result);
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
  }, [applyMutationState, beginAction, finishAction, reloadAfterInvalidState, state]);

  const deleteCurrentRequest = useCallback(async () => {
    if (!state?.request) return false;
    const requestId = state.request.id;
    const actionKey = `${requestId}:delete`;
    if (!beginAction(actionKey)) return false;
    setExitError(null);
    try {
      await deleteSolarRequest(requestId);
      stateRequestIdRef.current += 1;
      stateInFlightRef.current = null;
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

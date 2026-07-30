import { useFocusEffect } from '@react-navigation/native';
import { useCallback, useRef, useState } from 'react';

import { ApiClientError } from '@/src/services/api/client';

import { getPlanManagementState } from '../api/plan-management-state';
import {
  createSolarRequest,
  deleteSolarRequest,
  reopenSolarRequest,
  sendSolarMessage,
  submitSolarDecision,
} from '../api/solar-requests';
import type { DecisionOption, PlanManagementState, RequestPurpose } from '../types';
import { generateClientEventId } from '../utils/client-event-id';

const GENERIC_ACTION_ERROR_MESSAGE = '정보를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.';

export function usePlanManagement() {
  const [state, setState] = useState<PlanManagementState | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [hasLoadError, setHasLoadError] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [exitError, setExitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const pendingActionRef = useRef<string | null>(null);

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

  // GET /plan-management/state 하나로 screenMode와 request 전체(messages/requestItems/...)를
  // 함께 받으므로, 상태 복원을 위해 GET /solar/requests/{id}를 추가로 호출하지 않는다.
  const load = useCallback(async () => {
    setIsLoading(true);
    setHasLoadError(false);
    try {
      const result = await getPlanManagementState();
      setState(result);
    } catch {
      setHasLoadError(true);
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

  // 탭 포커스마다 최신 상태로 다시 조회한다. 대화 기록은 탭을 벗어나면 로컬 상태에서
  // 사라지고 다음 포커스 때 서버 상태로 복원된다(캡처의 "대화 기록은 이 탭을 벗어나면
  // 사라져요" 안내와 일치).
  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

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
    isSubmitting,
    reload: load,
    submitInitialMessage,
    sendAnswer,
    submitDecision,
    reopenRequest,
    deleteCurrentRequest,
    clearActionError: () => setActionError(null),
    clearExitError: () => setExitError(null),
  };
}

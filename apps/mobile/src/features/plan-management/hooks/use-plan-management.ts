import { useFocusEffect } from '@react-navigation/native';
import { useCallback, useState } from 'react';

import { ApiClientError } from '@/src/services/api/client';

import { getPlanManagementState } from '../api/plan-management-state';
import { createSolarRequest, sendSolarMessage } from '../api/solar-requests';
import type { PlanManagementState, RequestPurpose } from '../types';
import { generateClientEventId } from '../utils/client-event-id';

const GENERIC_ACTION_ERROR_MESSAGE = '정보를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.';

export function usePlanManagement() {
  const [state, setState] = useState<PlanManagementState | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [hasLoadError, setHasLoadError] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

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
      if (isSubmitting) return;
      setIsSubmitting(true);
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
        setIsSubmitting(false);
      }
    },
    [isSubmitting, load]
  );

  const sendAnswer = useCallback(
    async (message: string) => {
      if (isSubmitting || !state || !state.request) return;
      const requestId = state.request.id;
      setIsSubmitting(true);
      setActionError(null);
      try {
        const result = await sendSolarMessage(requestId, {
          clientEventId: generateClientEventId(),
          message,
        });
        setState(result);
      } catch (error) {
        // 오류가 나면 화면과 기존 요청 데이터를 그대로 유지하고 오류만 보여준다.
        setActionError(error instanceof ApiClientError ? error.message : GENERIC_ACTION_ERROR_MESSAGE);
      } finally {
        setIsSubmitting(false);
      }
    },
    [isSubmitting, state]
  );

  return {
    state,
    isLoading,
    hasLoadError,
    actionError,
    isSubmitting,
    reload: load,
    submitInitialMessage,
    sendAnswer,
    clearActionError: () => setActionError(null),
  };
}

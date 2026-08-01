import { apiRequest } from '@/src/services/api/client';

import { normalizeExecutionStatusResponse, normalizePlanManagementState } from '../logic';
import type {
  AcknowledgeExecutionResultResponse,
  DecisionOption,
  ExecutionStartResponse,
  ExecutionStatusResponse,
  PlanManagementState,
  RequestPurpose,
} from '../types';

type CreateSolarRequestBody = {
  purpose: RequestPurpose;
  clientEventId: string;
  message: string;
};

export async function createSolarRequest(body: CreateSolarRequestBody): Promise<PlanManagementState> {
  const result = await apiRequest<PlanManagementState>('/solar/requests', { method: 'POST', body });
  return normalizePlanManagementState(result);
}

// GET /plan-management/state가 이미 request 전체를 포함해 반환하므로, 이 함수는 상태 복원에
// 실제로 필요한 경우(예: 딥링크로 특정 요청에 바로 진입)에만 별도로 호출한다.
// 탭 포커스 시 일반 상태 로딩(usePlanManagement의 load)에서는 호출하지 않는다.
export async function getSolarRequestDetail(requestId: string): Promise<PlanManagementState> {
  const result = await apiRequest<PlanManagementState>(`/solar/requests/${requestId}`);
  return normalizePlanManagementState(result);
}

type SendSolarMessageBody = {
  clientEventId: string;
  message: string;
};

export async function sendSolarMessage(
  requestId: string,
  body: SendSolarMessageBody
): Promise<PlanManagementState> {
  const result = await apiRequest<PlanManagementState>(`/solar/requests/${requestId}/messages`, {
    method: 'POST',
    body,
  });
  return normalizePlanManagementState(result);
}

type SubmitSolarDecisionBody = {
  clientEventId: string;
  decision: DecisionOption['value'];
};

export async function submitSolarDecision(
  requestId: string,
  body: SubmitSolarDecisionBody
): Promise<PlanManagementState> {
  const result = await apiRequest<PlanManagementState>(`/solar/requests/${requestId}/decisions`, {
    method: 'POST',
    body,
  });
  return normalizePlanManagementState(result);
}

export async function reopenSolarRequest(requestId: string): Promise<PlanManagementState> {
  const result = await apiRequest<PlanManagementState>(`/solar/requests/${requestId}/reopen`, {
    method: 'POST',
  });
  return normalizePlanManagementState(result);
}

export function executeSolarRequest(requestId: string): Promise<ExecutionStartResponse> {
  return apiRequest<ExecutionStartResponse>(`/solar/requests/${requestId}/execute`, {
    method: 'POST',
  });
}

export async function getSolarRequestExecution(requestId: string): Promise<ExecutionStatusResponse> {
  const result = await apiRequest<ExecutionStatusResponse>(`/solar/requests/${requestId}/execution`);
  return normalizeExecutionStatusResponse(result);
}

export function retrySolarRequest(requestId: string): Promise<ExecutionStartResponse> {
  return apiRequest<ExecutionStartResponse>(`/solar/requests/${requestId}/retry`, {
    method: 'POST',
  });
}

export function acknowledgeSolarRequestResult(
  requestId: string
): Promise<AcknowledgeExecutionResultResponse> {
  return apiRequest<AcknowledgeExecutionResultResponse>(
    `/solar/requests/${requestId}/acknowledge-result`,
    { method: 'POST' }
  );
}

export function deleteSolarRequest(requestId: string): Promise<void> {
  return apiRequest<void>(`/solar/requests/${requestId}`, {
    method: 'DELETE',
  });
}

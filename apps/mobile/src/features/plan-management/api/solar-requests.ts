import { apiRequest } from '@/src/services/api/client';

import type { PlanManagementState, RequestPurpose } from '../types';

type CreateSolarRequestBody = {
  purpose: RequestPurpose;
  clientEventId: string;
  message: string;
};

export function createSolarRequest(body: CreateSolarRequestBody): Promise<PlanManagementState> {
  return apiRequest<PlanManagementState>('/solar/requests', { method: 'POST', body });
}

// GET /plan-management/state가 이미 request 전체를 포함해 반환하므로, 이 함수는 상태 복원에
// 실제로 필요한 경우(예: 딥링크로 특정 요청에 바로 진입)에만 별도로 호출한다.
// 탭 포커스 시 일반 상태 로딩(usePlanManagement의 load)에서는 호출하지 않는다.
export function getSolarRequestDetail(requestId: string): Promise<PlanManagementState> {
  return apiRequest<PlanManagementState>(`/solar/requests/${requestId}`);
}

type SendSolarMessageBody = {
  clientEventId: string;
  message: string;
};

export function sendSolarMessage(
  requestId: string,
  body: SendSolarMessageBody
): Promise<PlanManagementState> {
  return apiRequest<PlanManagementState>(`/solar/requests/${requestId}/messages`, {
    method: 'POST',
    body,
  });
}

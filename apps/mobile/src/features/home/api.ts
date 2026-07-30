import { apiRequest } from '@/src/services/api/client';

import type {
  CheckInAcknowledgeResponse,
  DeadlineWarningsAcknowledgeResponse,
  HomeCurrentResponse,
  PlanBlockCheckStateResponse,
} from './types';

export function getHomeCurrent(): Promise<HomeCurrentResponse> {
  return apiRequest<HomeCurrentResponse>('/home/current');
}

// API 명세서 10-1: checked=true는 PLANNED→CHECKED, checked=false는 CHECKED→PLANNED.
export function patchPlanBlockCheckState(
  planBlockId: string,
  checked: boolean
): Promise<PlanBlockCheckStateResponse> {
  return apiRequest<PlanBlockCheckStateResponse>(`/plan-blocks/${planBlockId}/check-state`, {
    method: 'PATCH',
    body: { checked },
  });
}

// API 명세서 10-2: 화면에 표시된 blockingNotice.items의 taskId 전체를 한 번에 확인한다.
export function postDeadlineWarningsAcknowledge(taskIds: string[]): Promise<DeadlineWarningsAcknowledgeResponse> {
  return apiRequest<DeadlineWarningsAcknowledgeResponse>('/tasks/deadline-warnings/acknowledge', {
    method: 'POST',
    body: { taskIds },
  });
}

// API 명세서 10-3: request body 없음.
export function postCheckInAcknowledge(checkInId: string): Promise<CheckInAcknowledgeResponse> {
  return apiRequest<CheckInAcknowledgeResponse>(`/check-ins/${checkInId}/acknowledge`, {
    method: 'POST',
  });
}

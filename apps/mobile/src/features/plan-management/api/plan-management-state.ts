import { apiRequest } from '@/src/services/api/client';

import type { PlanManagementState } from '../types';

export function getPlanManagementState(): Promise<PlanManagementState> {
  return apiRequest<PlanManagementState>('/plan-management/state');
}

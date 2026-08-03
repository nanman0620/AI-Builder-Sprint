import { apiRequest } from '@/src/services/api/client';

import { normalizePlanManagementState } from '../logic';
import type { PlanManagementState } from '../types';

export async function getPlanManagementState(): Promise<PlanManagementState> {
  const result = await apiRequest<PlanManagementState>('/plan-management/state');
  return normalizePlanManagementState(result);
}

import { apiRequest } from '@/src/services/api/client';
import type { BootstrapResponse } from './types';

export function getBootstrap(): Promise<BootstrapResponse> {
  return apiRequest<BootstrapResponse>('/bootstrap');
}

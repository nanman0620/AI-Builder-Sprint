import { apiRequest } from '@/src/services/api/client';
import type { BootstrapResponse } from './types';

// accessToken은 호출자가 session 복원을 이미 확인한 뒤 넘긴 값이다 — 이 함수 안에서 다시
// getSession()을 조회하지 않아, session 복원 직후 호출인데도 다른 session 조회 결과 때문에
// Authorization 헤더가 비어 401이 나는 경우를 없앤다.
export function getBootstrap(accessToken: string): Promise<BootstrapResponse> {
  return apiRequest<BootstrapResponse>('/bootstrap', { accessToken });
}

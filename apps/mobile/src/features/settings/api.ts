import { apiRequest } from '@/src/services/api/client';

import type { Profile } from './types';

export async function getProfile(): Promise<Profile> {
  return apiRequest<Profile>('/me');
}

export async function updateProfileNickname(nickname: string): Promise<Profile> {
  return apiRequest<Profile>('/me/profile', {
    method: 'PATCH',
    body: { nickname },
  });
}

import { apiRequest } from '@/src/services/api/client';
import type { Profile } from '@/src/types/profile';

type PutOnboardingRequest = {
  nickname: string;
};

export function putOnboarding(nickname: string): Promise<Profile> {
  const body: PutOnboardingRequest = { nickname };
  return apiRequest<Profile>('/me/onboarding', { method: 'PUT', body });
}

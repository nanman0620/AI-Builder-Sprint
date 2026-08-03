// docs/api/이음_MVP_최종_API_명세서.pdf 3-1 Profile 스키마.
export type Profile = {
  id: string;
  email: string;
  nickname: string | null;
  onboardingCompleted: boolean;
  createdAt: string;
  updatedAt: string;
};

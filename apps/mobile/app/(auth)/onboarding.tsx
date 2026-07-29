import { RoutePlaceholder } from '@/src/components/common/route-placeholder';

export default function OnboardingScreen() {
  return (
    <RoutePlaceholder
      title="닉네임 생성"
      description="온보딩 완료 분기와 PUT /me/onboarding 연동은 후속 인증 Issue에서 구현합니다."
    />
  );
}

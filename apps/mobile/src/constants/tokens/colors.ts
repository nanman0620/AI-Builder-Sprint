// UI_REFERENCE.md에 정확한 hex 값이 없어 docs/design/ui/screens/의 캡처(UI-001, 002, 005, 007, 009, 011, 020, 027, 032)를
// 육안으로 대조해 만든 근사값이다. Figma 실측값이 아니므로 실제 화면 구현 시 다시 확인한다.
export const colors = {
  background: '#FFFFFF',
  surface: '#FFFFFF',
  text: '#111827',
  textSecondary: '#6B7280',
  primary: '#CB72FF',
  error: '#EF4444',
  border: '#E5E7EB',
  // 완료된 PlanBlock 카드, 진행률 게이지 트랙, 프로필 아바타 배경 등에서 반복되는 옅은 보라 표면 (UI-007, UI-011, UI-027)
  primarySoft: '#F3E8FF',
  // 마감 임박(DEADLINE_WARNING) 배지·카드에서 반복되는 주황 계열 경고색 (UI-008, UI-009)
  warning: '#F59E0B',
} as const;

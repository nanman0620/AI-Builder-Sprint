import type { ViewStyle } from 'react-native';

export const TAB_BAR_BASE_HEIGHT = 49;
export const TAB_BAR_HEIGHT = TAB_BAR_BASE_HEIGHT + 8;
export const TAB_BAR_ASSET_HEIGHT = 44;
export const TAB_BAR_DIVIDER_GAP = Math.round(TAB_BAR_ASSET_HEIGHT / 3);
export const TAB_BAR_DIVIDER_HEIGHT = 1.5;
// 390×844에서 현재 tabAsset 상단은 tab bar 상단보다 3dp 위에 렌더링된다.
export const TAB_BAR_ASSET_TOP_FROM_BAR = -3;
export const TAB_BAR_DIVIDER_TOP =
  TAB_BAR_ASSET_TOP_FROM_BAR - TAB_BAR_DIVIDER_GAP - TAB_BAR_DIVIDER_HEIGHT;
export const PLAN_COMPOSER_DIVIDER_GAP = 12;
// 계획관리 화면 콘텐츠는 tab bar 상단에서 끝나므로 divider의 음수 top만큼 올린 뒤 12dp를 더 띄운다.
export const PLAN_COMPOSER_BOTTOM_OFFSET = -TAB_BAR_DIVIDER_TOP + PLAN_COMPOSER_DIVIDER_GAP;
export const PLAN_COMPOSER_RESTING_BOTTOM_MARGIN = PLAN_COMPOSER_BOTTOM_OFFSET - 4;

export function getTabBarStyle(bottomInset: number, hidden = false): ViewStyle {
  return {
    // React Navigation의 기본 상단 border는 별도 divider와 겹치지 않도록 비활성화한다.
    backgroundColor: 'transparent',
    borderTopWidth: 0,
    height: TAB_BAR_HEIGHT + bottomInset,
    ...(hidden ? { display: 'none' } : null),
  };
}

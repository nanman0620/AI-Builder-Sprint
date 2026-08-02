export const LOGOUT_SHEET_BASE_BOTTOM_SPACING = 40;

export function getLogoutSheetPaddingBottom(bottomInset: number): number {
  return LOGOUT_SHEET_BASE_BOTTOM_SPACING + Math.max(0, bottomInset);
}

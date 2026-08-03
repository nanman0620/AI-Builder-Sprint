import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { resolve } from 'node:path';

const modalSource = readFileSync(
  resolve(process.cwd(), 'src/features/settings/components/LogoutConfirmModal.tsx'),
  'utf8'
);
const layoutSource = readFileSync(
  resolve(process.cwd(), 'src/features/settings/components/logout-confirm-modal-layout.ts'),
  'utf8'
);
const BASE_BOTTOM_SPACING = 40;

function expectedPaddingBottom(bottomInset: number): number {
  return BASE_BOTTOM_SPACING + Math.max(0, bottomInset);
}

test('bottom inset이 0이면 기본 하단 여백만 적용한다', () => {
  assert.equal(expectedPaddingBottom(0), BASE_BOTTOM_SPACING);
});

test('system bottom inset을 기본 하단 여백에 한 번 더한다', () => {
  assert.equal(expectedPaddingBottom(24), BASE_BOTTOM_SPACING + 24);
  assert.equal(expectedPaddingBottom(-1), BASE_BOTTOM_SPACING);
  assert.match(layoutSource, /LOGOUT_SHEET_BASE_BOTTOM_SPACING = 40/);
  assert.match(layoutSource, /LOGOUT_SHEET_BASE_BOTTOM_SPACING \+ Math\.max\(0, bottomInset\)/);
});

test('로그아웃 sheet가 safe-area inset과 기존 닫기 동작을 유지한다', () => {
  assert.match(modalSource, /useSafeAreaInsets\(\)/);
  assert.match(modalSource, /getLogoutSheetPaddingBottom\(bottomInset\)/);
  assert.doesNotMatch(modalSource, /sheet:\s*\{[\s\S]*?paddingBottom:\s*40/);
  assert.match(modalSource, /onRequestClose=\{onCancel\}/);
  assert.match(modalSource, /onPress=\{onCancel\}/);
  assert.match(modalSource, /onPress=\{onConfirm\}/);
  assert.match(modalSource, /statusBarTranslucent/);
});

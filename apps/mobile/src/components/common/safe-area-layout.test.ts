import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { test } from 'node:test';

function source(path: string): string {
  return readFileSync(resolve(process.cwd(), path), 'utf8');
}

const rootLayout = source('app/_layout.tsx');
const tabsLayout = source('app/(tabs)/_layout.tsx');
const authLayout = source('app/(auth)/_layout.tsx');
const safeAreaScreen = source('src/components/common/safe-area-screen.tsx');
const tabBar = source('src/constants/tab-bar.ts');

test('root provides exactly one SafeAreaProvider', () => {
  assert.equal(rootLayout.match(/<SafeAreaProvider>/g)?.length, 1);
  assert.equal(rootLayout.match(/<\/SafeAreaProvider>/g)?.length, 1);
});

test('tab scenes own native top safe area without wrapping the navigator or taking bottom responsibility', () => {
  assert.match(tabsLayout, /paddingTop: Platform\.OS === 'web' \? 0 : topInset/);
  assert.doesNotMatch(tabsLayout, /<SafeAreaScreen/);
  assert.match(tabsLayout, /<PlanExitGuardProvider>\s*<GuardedTabs \/>/);
  assert.match(tabsLayout, /tabBarStyle: getTabBarStyle\(bottomInset\)/);
  assert.match(tabsLayout, /tabBarHideOnKeyboard: true/);
  assert.match(tabBar, /height: TAB_BAR_HEIGHT \+ bottomInset/);
});

test('web tab content keeps a centered mobile reading width without changing the tab bar', () => {
  assert.match(tabsLayout, /Platform\.OS === 'web'[\s\S]*?width: '100%'[\s\S]*?maxWidth: 480[\s\S]*?alignSelf: 'center'/);
  assert.doesNotMatch(tabBar, /maxWidth|alignSelf/);
});

test('tab scene safe area does not change the existing keyboard-avoiding plan composer', () => {
  for (const path of [
    'src/features/plan-management/components/entry-screen.tsx',
    'src/features/plan-management/components/collecting-screen.tsx',
    'src/features/plan-management/components/change-input-screen.tsx',
  ]) {
    assert.match(source(path), /<PlanKeyboardLayout>/);
    assert.match(source(path), /<MessageInput/);
  }
});

test('plan composer follows the real iOS keyboard frame with a small gap', () => {
  const keyboardLayout = source(
    'src/features/plan-management/components/plan-keyboard-layout.tsx',
  );
  assert.match(keyboardLayout, /keyboardWillChangeFrame/);
  assert.match(keyboardLayout, /windowHeight - event\.endCoordinates\.screenY/);
  assert.match(keyboardLayout, /COMPOSER_KEYBOARD_GAP = 8/);
  assert.match(
    keyboardLayout,
    /keyboardInset \+ COMPOSER_KEYBOARD_GAP - PLAN_COMPOSER_RESTING_BOTTOM_MARGIN/,
  );
  assert.match(keyboardLayout, /paddingBottom: keyboardPadding/);
  assert.match(keyboardLayout, /Platform\.OS === 'android'[\s\S]*?behavior="height"/);
});

test('auth shell owns top and bottom safe areas while web keeps existing spacing', () => {
  assert.match(authLayout, /<SafeAreaScreen edges=\{\['top', 'bottom'\]\}>/);
  assert.match(safeAreaScreen, /Platform\.OS === 'web' \? \[\] : edges/);
});

test('feature screens do not duplicate shell top safe area', () => {
  for (const path of [
    'src/features/auth/screens/login-screen.tsx',
    'src/features/auth/screens/sign-up-screen.tsx',
    'src/features/onboarding/screens/onboarding-screen.tsx',
    'app/(tabs)/settings/index.tsx',
    'app/(tabs)/settings/profile.tsx',
  ]) {
    assert.doesNotMatch(source(path), /SafeAreaView|SafeAreaScreen/);
  }
});

test('standalone withdrawal screen owns native top and bottom safe areas', () => {
  assert.match(
    source('app/account-withdrawal.tsx'),
    /<SafeAreaScreen edges=\{\['top', 'bottom'\]\}/,
  );
});

// 순수 함수 테스트다. React Native/Expo 의존성이 없어 로컬 tsc로 CommonJS로 컴파일한 뒤
// `node --test`로 실행할 수 있다. 실행 방법은 이 Issue의 최종 보고를 참고한다.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { resolveAppRoute, resolveInitialRoute, type BootstrapSyncResult } from './route';
import type { BootstrapResponse } from './types';

function makeBootstrap(overrides: Partial<BootstrapResponse> = {}): BootstrapResponse {
  return {
    serverTime: '2026-07-30T14:00:00+09:00',
    profile: {
      id: 'user-1',
      email: 'user@example.com',
      nickname: '유림',
      onboardingCompleted: true,
    },
    initialScreen: 'IN_PROGRESS',
    activeCycle: null,
    planManagement: null,
    home: null,
    ...overrides,
  };
}

test('session 없음 → 로그인', () => {
  const result: BootstrapSyncResult = { type: 'no-session' };
  assert.deepEqual(resolveAppRoute(result), { type: 'route', href: '/(auth)/login' });
});

test('AUTH_REQUIRED → 로그인', () => {
  const result: BootstrapSyncResult = { type: 'auth-required' };
  assert.deepEqual(resolveAppRoute(result), { type: 'route', href: '/(auth)/login' });
});

test('bootstrap 네트워크·서버 오류 → error', () => {
  const result: BootstrapSyncResult = { type: 'error', error: new Error('network') };
  assert.deepEqual(resolveAppRoute(result), { type: 'error' });
});

test('onboardingCompleted=false → 온보딩', () => {
  const bootstrap = makeBootstrap({
    profile: { id: 'u', email: 'e@x.com', nickname: null, onboardingCompleted: false },
    initialScreen: 'IN_PROGRESS',
  });
  assert.deepEqual(resolveInitialRoute(bootstrap), { type: 'route', href: '/(auth)/onboarding' });
});

test('initialScreen=NICKNAME_CREATION → 온보딩', () => {
  const bootstrap = makeBootstrap({ initialScreen: 'NICKNAME_CREATION' });
  assert.deepEqual(resolveInitialRoute(bootstrap), { type: 'route', href: '/(auth)/onboarding' });
});

const PLAN_MANAGEMENT_SCREENS = [
  'COLLECTING',
  'CHANGE_CONFIRMATION',
  'CHANGE_INPUT',
  'FINAL_REVIEW',
  'EXECUTING',
  'EXECUTION_SUCCESS',
  'EXECUTION_FAILED',
];

for (const screen of PLAN_MANAGEMENT_SCREENS) {
  test(`initialScreen=${screen} → 계획관리 Route`, () => {
    const bootstrap = makeBootstrap({ initialScreen: screen });
    assert.deepEqual(resolveInitialRoute(bootstrap), { type: 'route', href: '/(tabs)/plan-management' });
  });
}

const HOME_SCREENS = ['FINALIZING', 'CHECK_IN_RESULT', 'DEADLINE_WARNING', 'NO_ACTIVE_CYCLE', 'NO_PLANS', 'IN_PROGRESS'];

for (const screen of HOME_SCREENS) {
  test(`initialScreen=${screen} → 홈 Route`, () => {
    const bootstrap = makeBootstrap({ initialScreen: screen });
    assert.deepEqual(resolveInitialRoute(bootstrap), { type: 'route', href: '/(tabs)/home' });
  });
}

test('알 수 없는 initialScreen → 오류 상태', () => {
  const bootstrap = makeBootstrap({ initialScreen: 'SOMETHING_NEW' });
  assert.deepEqual(resolveInitialRoute(bootstrap), { type: 'unknown-screen', initialScreen: 'SOMETHING_NEW' });
});

test('resolveAppRoute는 success 결과를 resolveInitialRoute에 위임한다', () => {
  const bootstrap = makeBootstrap({ initialScreen: 'NO_PLANS' });
  const result: BootstrapSyncResult = { type: 'success', data: bootstrap };
  assert.deepEqual(resolveAppRoute(result), { type: 'route', href: '/(tabs)/home' });
});

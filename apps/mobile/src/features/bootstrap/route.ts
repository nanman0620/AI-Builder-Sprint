import type { BootstrapResponse } from './types';

// getBootstrap() 호출 하나의 결과를 표현한다. no-session은 Supabase session 자체가 없는 경우,
// auth-required는 서버가 401 AUTH_REQUIRED를 반환한 경우다. 두 경우 모두 로그인 화면으로 보낸다는
// 점은 같지만 auth-required는 기존 session 정리(로그아웃)가 추가로 필요하므로 구분해 둔다.
export type BootstrapSyncResult =
  | { type: 'no-session' }
  | { type: 'auth-required' }
  | { type: 'success'; data: BootstrapResponse }
  | { type: 'error'; error: unknown };

// docs/ai/IMPLEMENTATION_CONTEXT.md 4절 "초기 화면 우선순위" 중 계획관리 상태 5개.
const PLAN_MANAGEMENT_INITIAL_SCREENS = new Set<string>([
  'COLLECTING',
  'CHANGE_CONFIRMATION',
  'CHANGE_INPUT',
  'FINAL_REVIEW',
  'EXECUTING',
  'EXECUTION_SUCCESS',
  'EXECUTION_FAILED',
]);

// 같은 절의 홈 상태 6개.
const HOME_INITIAL_SCREENS = new Set<string>([
  'FINALIZING',
  'CHECK_IN_RESULT',
  'DEADLINE_WARNING',
  'NO_ACTIVE_CYCLE',
  'NO_PLANS',
  'IN_PROGRESS',
]);

// getSession() 결과 하나를 bootstrap 호출 여부·사용할 token으로 변환하는 순수 함수.
// session이 아직 복원되지 않았거나 없으면(null) 절대 GET /bootstrap을 호출하지 않는다 — 이
// 검사와 실제 호출 사이에 session을 다시 조회하지 않으므로 두 조회 결과가 서로 달라 인증 헤더
// 없이 요청이 나가는 경우가 없다.
export type SessionGateResult =
  | { type: 'no-session' }
  | { type: 'call-bootstrap'; accessToken: string };

export function resolveSessionGate(session: { access_token: string } | null): SessionGateResult {
  if (!session) {
    return { type: 'no-session' };
  }
  return { type: 'call-bootstrap', accessToken: session.access_token };
}

export type AppRouteHref = '/(auth)/login' | '/(auth)/onboarding' | '/(tabs)/plan-management' | '/(tabs)/home';

export type AppRouteDecision =
  | { type: 'route'; href: AppRouteHref }
  | { type: 'error' }
  | { type: 'unknown-screen'; initialScreen: string };

// bootstrap 응답 하나를 최초 Route로 변환하는 순수 함수.
// 서버가 계산한 initialScreen을 그대로 분기하며 activeRequest.status 등으로 다시 계산하지 않는다.
export function resolveInitialRoute(bootstrap: BootstrapResponse): AppRouteDecision {
  if (!bootstrap.profile.onboardingCompleted || bootstrap.initialScreen === 'NICKNAME_CREATION') {
    return { type: 'route', href: '/(auth)/onboarding' };
  }

  if (PLAN_MANAGEMENT_INITIAL_SCREENS.has(bootstrap.initialScreen)) {
    return { type: 'route', href: '/(tabs)/plan-management' };
  }

  if (HOME_INITIAL_SCREENS.has(bootstrap.initialScreen)) {
    return { type: 'route', href: '/(tabs)/home' };
  }

  // 알 수 없는 initialScreen을 조용히 홈으로 보내지 않고 호출자가 전체 오류 상태로 처리하게 한다.
  return { type: 'unknown-screen', initialScreen: bootstrap.initialScreen };
}

// session 확인부터 bootstrap 호출까지의 전체 결과를 최초 Route로 변환하는 순수 함수.
export function resolveAppRoute(result: BootstrapSyncResult): AppRouteDecision {
  if (result.type === 'no-session' || result.type === 'auth-required') {
    return { type: 'route', href: '/(auth)/login' };
  }

  if (result.type === 'error') {
    return { type: 'error' };
  }

  return resolveInitialRoute(result.data);
}

import * as Linking from 'expo-linking';
import * as WebBrowser from 'expo-web-browser';
import type { Session } from '@supabase/supabase-js';

import { getSupabaseClient } from '@/src/services/supabase/client';

// 웹에서 OAuth 팝업/탭이 앱으로 정상 복귀하도록 모듈 로드 시 한 번 호출한다.
WebBrowser.maybeCompleteAuthSession();

export type SignInResult = { status: 'success'; session: Session } | { status: 'error'; error: unknown };

export type SignUpResult =
  | { status: 'success'; session: Session }
  | { status: 'no-session' }
  | { status: 'error'; error: unknown };

export type KakaoSignInResult =
  | { status: 'success'; session: Session }
  | { status: 'cancelled' }
  | { status: 'error' };

export type SignOutOptions = { scope?: 'global' | 'local' | 'others' };

// bootstrap의 AUTH_REQUIRED 처리(로그인 Route 이동 전 session 정리)가 사용한다.
// options 생략 시 기존과 동일하게 supabase-js 기본값(scope: 'global')으로 동작한다.
export async function signOut(options?: SignOutOptions): Promise<void> {
  await getSupabaseClient().auth.signOut(options);
}

export async function signInWithEmail(email: string, password: string): Promise<SignInResult> {
  const { data, error } = await getSupabaseClient().auth.signInWithPassword({ email, password });
  if (error) {
    return { status: 'error', error };
  }
  return { status: 'success', session: data.session };
}

export async function signUpWithEmail(email: string, password: string): Promise<SignUpResult> {
  const { data, error } = await getSupabaseClient().auth.signUp({ email, password });
  if (error) {
    return { status: 'error', error };
  }
  if (!data.session) {
    return { status: 'no-session' };
  }
  return { status: 'success', session: data.session };
}

function parseFragmentParams(url: string): Record<string, string> {
  const fragmentStart = url.indexOf('#');
  if (fragmentStart === -1) {
    return {};
  }
  return Object.fromEntries(new URLSearchParams(url.slice(fragmentStart + 1)));
}

// 콜백 URL 형태를 하나로 단정하지 않는다: PKCE의 code 쿼리 파라미터와
// implicit flow의 access_token/refresh_token 해시 프래그먼트를 모두 방어적으로 확인한다.
// 현재 Supabase client의 flowType은 'implicit'(기본값, 미변경)이라 해시 경로가 주로 사용된다.
export async function signInWithKakao(): Promise<KakaoSignInResult> {
  const supabase = getSupabaseClient();
  const redirectTo = Linking.createURL('/login');

  const { data, error } = await supabase.auth.signInWithOAuth({
    provider: 'kakao',
    options: { redirectTo, skipBrowserRedirect: true },
  });

  if (error || !data?.url) {
    return { status: 'error' };
  }

  const authResult = await WebBrowser.openAuthSessionAsync(data.url, redirectTo);

  if (authResult.type !== 'success') {
    // 사용자가 인증창을 취소·닫은 경우: 오류 없이 로그인 화면을 유지하고 재시도 가능하게 둔다.
    return { status: 'cancelled' };
  }

  const { queryParams } = Linking.parse(authResult.url);
  const fragmentParams = parseFragmentParams(authResult.url);

  const oauthErrorParam =
    (typeof queryParams?.error_description === 'string' && queryParams.error_description) ||
    (typeof queryParams?.error === 'string' && queryParams.error) ||
    fragmentParams.error_description ||
    fragmentParams.error;

  if (oauthErrorParam) {
    return { status: 'error' };
  }

  const code = typeof queryParams?.code === 'string' ? queryParams.code : undefined;

  if (code) {
    const { error: exchangeError } = await supabase.auth.exchangeCodeForSession(code);
    if (exchangeError) {
      return { status: 'error' };
    }
  } else if (fragmentParams.access_token && fragmentParams.refresh_token) {
    const { error: setSessionError } = await supabase.auth.setSession({
      access_token: fragmentParams.access_token,
      refresh_token: fragmentParams.refresh_token,
    });
    if (setSessionError) {
      return { status: 'error' };
    }
  } else {
    return { status: 'error' };
  }

  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session) {
    return { status: 'error' };
  }

  return { status: 'success', session };
}

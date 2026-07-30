import { isAuthApiError, isAuthRetryableFetchError, isAuthWeakPasswordError } from '@supabase/supabase-js';

export const AUTH_NETWORK_ERROR_MESSAGE = '정보를 불러오지 못했어요.\n잠시 후 다시 시도해 주세요.';

const LOGIN_FAILED_MESSAGE = '이메일 또는 비밀번호를 확인해 주세요.';
const EMAIL_ALREADY_EXISTS_MESSAGE = '이미 가입된 이메일이에요.';
const WEAK_PASSWORD_MESSAGE = '비밀번호 조건을 확인해 주세요.';

// 로그인 실패는 어떤 값이 틀렸는지 단정하지 않고 공통 문구 하나로만 안내한다(도구·명세 확정 규칙).
export function toLoginErrorMessage(error: unknown): string {
  if (isAuthRetryableFetchError(error)) {
    return AUTH_NETWORK_ERROR_MESSAGE;
  }
  if (isAuthApiError(error)) {
    return LOGIN_FAILED_MESSAGE;
  }
  return AUTH_NETWORK_ERROR_MESSAGE;
}

export type SignUpErrorTarget = {
  field: 'email' | 'password' | 'general';
  message: string;
};

// error.code를 우선 판별하고, code가 없는 구버전 호환 상황에서만 message를 보조로 확인한다.
export function toSignUpErrorMessage(error: unknown): SignUpErrorTarget {
  if (isAuthRetryableFetchError(error)) {
    return { field: 'general', message: AUTH_NETWORK_ERROR_MESSAGE };
  }
  if (isAuthWeakPasswordError(error)) {
    return { field: 'password', message: WEAK_PASSWORD_MESSAGE };
  }
  if (isAuthApiError(error)) {
    if (error.code === 'user_already_exists' || error.code === 'email_exists') {
      return { field: 'email', message: EMAIL_ALREADY_EXISTS_MESSAGE };
    }
    if (error.code === 'weak_password') {
      return { field: 'password', message: WEAK_PASSWORD_MESSAGE };
    }
    if (!error.code) {
      if (/already registered|already exists/i.test(error.message)) {
        return { field: 'email', message: EMAIL_ALREADY_EXISTS_MESSAGE };
      }
      if (/password/i.test(error.message)) {
        return { field: 'password', message: WEAK_PASSWORD_MESSAGE };
      }
    }
  }
  return { field: 'general', message: AUTH_NETWORK_ERROR_MESSAGE };
}

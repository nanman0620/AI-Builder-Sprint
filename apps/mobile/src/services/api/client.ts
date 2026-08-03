import { getSupabaseClient } from '@/src/services/supabase/client';
import { env } from '@/src/utils/env';
import type { ApiErrorBody, ApiFailure, ApiSuccess } from '@/src/types/api';

type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';

type RequestOptions = {
  method?: HttpMethod;
  headers?: Record<string, string>;
  body?: unknown;
  // 호출자가 이미 session을 확인해 access_token을 갖고 있으면(예: bootstrap 최초 동기화)
  // 이 값을 그대로 쓰고, 이 함수 안에서 getSession()을 다시 호출하지 않는다 — 같은 요청 안에서
  // session을 두 번 독립적으로 조회해 서로 다른 결과를 받는 경우를 없앤다.
  accessToken?: string;
};

// 서버가 실제로 정의한 code가 아니라 네트워크 실패·비-JSON 응답 등 클라이언트 쪽에서만 발생하는 상황을 표시하는 값이다.
const NETWORK_ERROR: ApiErrorBody = {
  code: 'CLIENT_NETWORK_ERROR',
  message: '정보를 불러오지 못했어요.',
  details: null,
  traceId: null,
};

export class ApiClientError extends Error {
  readonly code: string;
  readonly details: unknown;
  readonly traceId: string | null;

  constructor(error: ApiErrorBody) {
    super(error.message);
    this.code = error.code;
    this.details = error.details ?? null;
    this.traceId = error.traceId ?? null;
  }
}

// 실제 endpoint 함수(예: getBootstrap, postSolarRequest 등)는 이 Issue에서 만들지 않는다.
// 인증 Issue·각 기능 Issue에서 이 함수를 사용해 21개 endpoint 호출을 구현한다.
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const url = `${env.apiBaseUrl}${path}`;
  const body = options.body !== undefined ? JSON.stringify(options.body) : undefined;

  const headers = new Headers(options.headers);
  if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (!headers.has('Authorization')) {
    if (options.accessToken) {
      headers.set('Authorization', `Bearer ${options.accessToken}`);
    } else {
      // 세션 조회 자체가 실패해도(예: 토큰 갱신 네트워크 오류) 요청을 막지 않고 인증 헤더 없이 계속 진행한다.
      // 실제 인증 필요 여부는 서버의 401 AUTH_REQUIRED 응답이 판단한다.
      try {
        const {
          data: { session },
        } = await getSupabaseClient().auth.getSession();
        if (session?.access_token) {
          headers.set('Authorization', `Bearer ${session.access_token}`);
        }
      } catch {
        // 세션 조회 실패는 무시한다. token이나 오류 내용을 로그로 남기지 않는다.
      }
    }
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method: options.method ?? 'GET',
      headers,
      body,
    });
  } catch {
    throw new ApiClientError(NETWORK_ERROR);
  }

  // bootstrap은 전달받은 token으로 자체 복구 순서를 관리한다. 그 외 API는 저장 session이
  // 만료된 경우에만 한 번 refresh하고 같은 요청을 재전송한다. 첫 401은 인증 계층에서
  // action이 실행되기 전에 거절된 응답이므로 mutation도 이 단회 재시도가 안전하다.
  if (response.status === 401 && !options.accessToken) {
    try {
      const { data, error } = await getSupabaseClient().auth.refreshSession();
      const refreshedAccessToken = data.session?.access_token;
      if (!error && refreshedAccessToken) {
        headers.set('Authorization', `Bearer ${refreshedAccessToken}`);
        response = await fetch(url, {
          method: options.method ?? 'GET',
          headers,
          body,
        });
      }
    } catch {
      // refresh 실패 또는 재요청 전송 실패 시 첫 401을 기존 오류 처리로 전달한다.
    }
  }

  if (response.status === 204) {
    return undefined as T;
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ApiClientError(NETWORK_ERROR);
  }

  if (!response.ok) {
    const errorBody = (payload as Partial<ApiFailure>)?.error ?? NETWORK_ERROR;
    throw new ApiClientError(errorBody);
  }

  return (payload as ApiSuccess<T>).data;
}

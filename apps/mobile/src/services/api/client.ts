import { env } from '@/src/utils/env';
import type { ApiErrorBody, ApiFailure, ApiSuccess } from '@/src/types/api';

type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';

type RequestOptions = {
  method?: HttpMethod;
  headers?: Record<string, string>;
  body?: unknown;
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

  let response: Response;
  try {
    response = await fetch(url, {
      method: options.method ?? 'GET',
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });
  } catch {
    throw new ApiClientError(NETWORK_ERROR);
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

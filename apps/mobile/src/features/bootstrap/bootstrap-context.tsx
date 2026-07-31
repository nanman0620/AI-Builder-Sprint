import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';

import { signOut } from '@/src/features/auth/services/auth-service';
import { ApiClientError } from '@/src/services/api/client';
import { getSupabaseClient } from '@/src/services/supabase/client';

import { getBootstrap } from './api';
import type { BootstrapSyncResult } from './route';
import type { BootstrapResponse } from './types';

export type BootstrapStatus = 'idle' | 'loading' | 'success' | 'error';

type BootstrapContextValue = {
  status: BootstrapStatus;
  data: BootstrapResponse | null;
  error: unknown;
  // session 재확인 → GET /bootstrap 호출까지 한 번에 수행한다. 이미 진행 중인 호출이 있으면
  // 새 요청을 만들지 않고 진행 중인 결과를 그대로 반환해 중복 호출을 막는다.
  sync: () => Promise<BootstrapSyncResult>;
  reset: () => void;
};

const BootstrapContext = createContext<BootstrapContextValue | null>(null);

export function BootstrapProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<BootstrapStatus>('idle');
  const [data, setData] = useState<BootstrapResponse | null>(null);
  const [error, setError] = useState<unknown>(null);

  const isMountedRef = useRef(true);
  const latestRequestIdRef = useRef(0);
  const inFlightRef = useRef<Promise<BootstrapSyncResult> | null>(null);

  const reset = useCallback(() => {
    latestRequestIdRef.current += 1;
    inFlightRef.current = null;
    if (isMountedRef.current) {
      setStatus('idle');
      setData(null);
      setError(null);
    }
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const sync = useCallback((): Promise<BootstrapSyncResult> => {
    if (inFlightRef.current) {
      return inFlightRef.current;
    }

    const requestId = ++latestRequestIdRef.current;
    if (isMountedRef.current) {
      setStatus('loading');
      setError(null);
    }

    const run = async (): Promise<BootstrapSyncResult> => {
      let result: BootstrapSyncResult;

      try {
        const {
          data: { session },
        } = await getSupabaseClient().auth.getSession();

        if (!session) {
          result = { type: 'no-session' };
        } else {
          const bootstrap = await getBootstrap();
          result = { type: 'success', data: bootstrap };
        }
      } catch (err) {
        if (err instanceof ApiClientError && err.code === 'AUTH_REQUIRED') {
          result = { type: 'auth-required' };
        } else {
          result = { type: 'error', error: err };
        }
      }

      if (result.type === 'auth-required') {
        try {
          await signOut();
        } catch {
          // 로그아웃 실패는 무시하고 로컬 상태만 정리한다. session이나 오류 내용을 로그로 남기지 않는다.
        }
      }

      // 오래된 요청 결과가 이후 요청 결과를 덮어쓰지 않도록, 가장 최근 요청일 때만 상태를 반영한다.
      if (isMountedRef.current && requestId === latestRequestIdRef.current) {
        if (result.type === 'success') {
          setStatus('success');
          setData(result.data);
          setError(null);
        } else if (result.type === 'error') {
          setStatus('error');
          setError(result.error);
        } else {
          // no-session · auth-required: 화면 이동은 호출자가 담당하고 전역 상태는 초기화한다.
          setStatus('idle');
          setData(null);
          setError(null);
        }
      }

      return result;
    };

    const promise = run().finally(() => {
      if (inFlightRef.current === promise) {
        inFlightRef.current = null;
      }
    });
    inFlightRef.current = promise;
    return promise;
  }, []);

  // 웹에서 /home 같은 직접 Route를 새로고침하면 app/index.tsx가 mount되지 않으므로,
  // Provider가 세션 복원 후 bootstrap을 최초 한 번 동기화한다. index·포그라운드 sync와 겹쳐도
  // inFlightRef가 같은 Promise를 반환해 GET /bootstrap 중복 요청을 만들지 않는다.
  useEffect(() => {
    void sync();
  }, [sync]);

  const value: BootstrapContextValue = { status, data, error, sync, reset };

  return <BootstrapContext.Provider value={value}>{children}</BootstrapContext.Provider>;
}

export function useBootstrap(): BootstrapContextValue {
  const ctx = useContext(BootstrapContext);
  if (!ctx) {
    throw new Error('useBootstrap은 BootstrapProvider 내부에서만 사용할 수 있습니다.');
  }
  return ctx;
}

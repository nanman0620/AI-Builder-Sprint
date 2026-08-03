import AsyncStorage from '@react-native-async-storage/async-storage';
import { createClient, processLock, type SupabaseClient } from '@supabase/supabase-js';
import { AppState, Platform } from 'react-native';

import { env } from '@/src/utils/env';

let client: SupabaseClient | null = null;

// @supabase/supabase-js가 storageKey를 안 넘기면 내부적으로 계산하는 기본값과 동일한 식이다
// (node_modules/@supabase/supabase-js/src/SupabaseClient.ts의 defaultStorageKey 계산 확인).
// 회원탈퇴 실패 시 이 정확한 키만 강제로 지우는 fallback(auth-service.ts의
// forceClearLocalSession)이 있어 명시적 상수로 고정해둔다 — 값 자체는 기존 암묵적 기본값과
// 같으므로 여기서 상수로 뽑아낸다고 기존 로그인 세션이 무효화되지 않는다.
export function computeAuthStorageKey(supabaseUrl: string): string {
  return `sb-${new URL(supabaseUrl).hostname.split('.')[0]}-auth-token`;
}

export const SUPABASE_AUTH_STORAGE_KEY = computeAuthStorageKey(env.supabaseUrl);

// 실제 로그인·회원가입·세션 조회 호출은 이 Issue의 범위가 아니며, 인증 Issue에서 이 client를 사용해 구현한다.
export function getSupabaseClient(): SupabaseClient {
  if (!client) {
    client = createClient(env.supabaseUrl, env.supabaseAnonKey, {
      auth: {
        storage: AsyncStorage,
        storageKey: SUPABASE_AUTH_STORAGE_KEY,
        autoRefreshToken: true,
        persistSession: true,
        detectSessionInUrl: false,
        lock: processLock,
      },
    });

    if (Platform.OS !== 'web') {
      if (AppState.currentState === 'active') {
        client.auth.startAutoRefresh();
      }
      AppState.addEventListener('change', (state) => {
        if (state === 'active') {
          client?.auth.startAutoRefresh();
        } else {
          client?.auth.stopAutoRefresh();
        }
      });
    }
  }
  return client;
}

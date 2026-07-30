import AsyncStorage from '@react-native-async-storage/async-storage';
import { createClient, type SupabaseClient } from '@supabase/supabase-js';

import { env } from '@/src/utils/env';

let client: SupabaseClient | null = null;

// 실제 로그인·회원가입·세션 조회 호출은 이 Issue의 범위가 아니며, 인증 Issue에서 이 client를 사용해 구현한다.
export function getSupabaseClient(): SupabaseClient {
  if (!client) {
    client = createClient(env.supabaseUrl, env.supabaseAnonKey, {
      auth: {
        storage: AsyncStorage,
        autoRefreshToken: true,
        persistSession: true,
        detectSessionInUrl: false,
      },
    });
  }
  return client;
}

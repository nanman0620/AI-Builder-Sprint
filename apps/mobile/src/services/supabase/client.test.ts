// SUPABASE_AUTH_STORAGE_KEY 계산식이 @supabase/supabase-js가 storageKey를 안 넘겼을 때
// 내부적으로 쓰는 기본값과 동일한지 고정하는 회귀 테스트
// (node_modules/@supabase/supabase-js/src/SupabaseClient.ts의 defaultStorageKey 계산 확인:
// `sb-${new URL(supabaseUrl).hostname.split('.')[0]}-auth-token`).
import assert from 'node:assert/strict';
import { test } from 'node:test';

process.env.EXPO_PUBLIC_SUPABASE_URL = 'https://abcxyz.supabase.co';
process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';

// eslint-disable-next-line import/first -- env vars above must be set before this import loads.
import { computeAuthStorageKey } from './client';

test('project ref만으로 sb-{ref}-auth-token 형태를 만든다', () => {
  assert.equal(computeAuthStorageKey('https://abcxyz.supabase.co'), 'sb-abcxyz-auth-token');
});

test('다른 project ref에도 동일한 규칙을 적용한다', () => {
  assert.equal(computeAuthStorageKey('https://my-project-ref.supabase.co'), 'sb-my-project-ref-auth-token');
});

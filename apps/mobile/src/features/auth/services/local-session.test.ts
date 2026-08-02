// forceClearLocalSession/isLocalSessionCleared 회귀 테스트. 정확히
// SUPABASE_AUTH_STORAGE_KEY와 그 code-verifier 키 두 개만 다루는지, 무관한 다른 sb- 키는
// 건드리지 않는지 확인한다(여러 Supabase 프로젝트/클라이언트가 공존해도 안전해야 함).
import assert from 'node:assert/strict';
import { test } from 'node:test';

process.env.EXPO_PUBLIC_SUPABASE_URL = 'https://abcxyz.supabase.co';
process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';

// eslint-disable-next-line import/first -- env vars above must be set before these imports load.
import AsyncStorage from '@react-native-async-storage/async-storage';
// eslint-disable-next-line import/first
import { forceClearLocalSession, isLocalSessionCleared } from './local-session';

const AUTH_KEY = 'sb-abcxyz-auth-token';
const CODE_VERIFIER_KEY = `${AUTH_KEY}-code-verifier`;
const UNRELATED_KEY = 'sb-other-project-auth-token';

test('forceClearLocalSession은 정확히 auth-token과 code-verifier 키만 multiRemove한다', async () => {
  const calls: string[][] = [];
  (AsyncStorage as any).multiRemove = async (keys: string[]) => {
    calls.push(keys);
  };

  await forceClearLocalSession();

  assert.equal(calls.length, 1);
  assert.deepEqual(new Set(calls[0]), new Set([AUTH_KEY, CODE_VERIFIER_KEY]));
  assert.ok(!calls[0].includes(UNRELATED_KEY));
});

test('isLocalSessionCleared는 두 키가 모두 null일 때만 true를 반환한다', async () => {
  (AsyncStorage as any).multiGet = async (keys: string[]) =>
    keys.map((key) => [key, null] as [string, string | null]);

  assert.equal(await isLocalSessionCleared(), true);
});

test('isLocalSessionCleared는 둘 중 하나라도 값이 남아있으면 false를 반환한다', async () => {
  (AsyncStorage as any).multiGet = async (keys: string[]) =>
    keys.map((key) => [key, key === AUTH_KEY ? 'still-here' : null] as [string, string | null]);

  assert.equal(await isLocalSessionCleared(), false);
});

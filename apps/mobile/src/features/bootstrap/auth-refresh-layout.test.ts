import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { test } from 'node:test';

function source(path: string): string {
  return readFileSync(resolve(process.cwd(), path), 'utf8');
}

const supabaseClient = source('src/services/supabase/client.ts');
const bootstrapContext = source('src/features/bootstrap/bootstrap-context.tsx');
const loginScreen = source('src/features/auth/screens/login-screen.tsx');

test('React Native Supabase client uses the official foreground refresh lifecycle and process lock', () => {
  assert.match(supabaseClient, /lock: processLock/);
  assert.match(supabaseClient, /AppState\.currentState === 'active'/);
  assert.match(supabaseClient, /client\.auth\.startAutoRefresh\(\)/);
  assert.match(supabaseClient, /client\?\.auth\.stopAutoRefresh\(\)/);
  assert.match(supabaseClient, /Platform\.OS !== 'web'/);
});

test('bootstrap retries once with a refreshed token before treating 401 as signed out', () => {
  assert.equal(bootstrapContext.match(/refreshAccessToken\(\)/g)?.length, 1);
  assert.match(
    bootstrapContext,
    /getBootstrap\(gate\.accessToken\)[\s\S]*?refreshAccessToken\(\)[\s\S]*?getBootstrap\(refreshedAccessToken\)/,
  );
  assert.match(bootstrapContext, /if \(!refreshedAccessToken\)[\s\S]*?type: 'auth-required'/);
});

test('a stale bootstrap 401 cannot sign out a newly authenticated session', () => {
  assert.match(bootstrapContext, /let attemptedAccessToken: string \| null = null/);
  assert.match(bootstrapContext, /attemptedAccessToken = gate\.accessToken/);
  assert.match(bootstrapContext, /attemptedAccessToken = refreshedAccessToken/);
  assert.match(
    bootstrapContext,
    /result\.type === 'auth-required' && requestId === latestRequestIdRef\.current/,
  );
  assert.match(
    bootstrapContext,
    /currentSession\?\.access_token === attemptedAccessToken[\s\S]*?await signOut\(\)/,
  );
});

test('successful authentication invalidates any bootstrap request started with the previous session', () => {
  assert.equal(loginScreen.match(/resetBootstrap\(\);[\s\S]*?router\.replace\('\/'\)/g)?.length, 2);
});

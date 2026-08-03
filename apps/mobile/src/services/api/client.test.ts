// apiRequest의 204 처리 회귀 테스트. DELETE /me(204)가 DELETE /solar/requests/{id}(204)와
// 같은 경로로 안전하게 동작함을 고정한다 — 서버가 204를 반환했는데 클라이언트가 response.json()을
// 시도해 파싱 실패로 catch에 빠지는 상황은 절대 없어야 한다.
import assert from 'node:assert/strict';
import { test } from 'node:test';

process.env.EXPO_PUBLIC_API_BASE_URL = 'https://api.example.com';
process.env.EXPO_PUBLIC_SUPABASE_URL = 'https://test-project.supabase.co';
process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';

// eslint-disable-next-line import/first -- env vars above must be set before this import loads.
import { apiRequest } from './client';

function makeResponse(status: number, options: { throwsOnJson?: boolean } = {}): Response {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: async () => {
      if (options.throwsOnJson) {
        throw new Error('204 응답에는 body가 없어 json()이 실패해야 한다');
      }
      return {};
    },
  } as unknown as Response;
}

test('204 응답은 response.json()을 시도하지 않고 undefined를 반환한다', async () => {
  const originalFetch = global.fetch;
  global.fetch = (async () => makeResponse(204, { throwsOnJson: true })) as typeof fetch;

  try {
    const result = await apiRequest('/me', { method: 'DELETE', accessToken: 'irrelevant' });
    assert.equal(result, undefined);
  } finally {
    global.fetch = originalFetch;
  }
});

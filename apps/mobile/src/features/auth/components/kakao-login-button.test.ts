import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { resolve } from 'node:path';

const buttonSource = readFileSync(
  resolve(process.cwd(), 'src/features/auth/components/kakao-login-button.tsx'),
  'utf8'
);
const loginSource = readFileSync(
  resolve(process.cwd(), 'src/features/auth/screens/login-screen.tsx'),
  'utf8'
);

test('카카오 전용 asset을 렌더링하고 일반 chat icon을 사용하지 않는다', () => {
  assert.match(buttonSource, /require\('@\/assets\/brand\/kakaotalk-seeklogo\.png'\)/);
  assert.doesNotMatch(buttonSource, /MaterialIcons|chat-bubble|chatbubble/);
  assert.match(buttonSource, /resizeMode="contain"/);
  assert.match(buttonSource, /accessible=\{false\}/);
  assert.match(buttonSource, /circle:\s*\{[\s\S]*?width: 40,[\s\S]*?height: 40/);
  assert.match(buttonSource, /logo:\s*\{[\s\S]*?width: 32,[\s\S]*?height: 32/);
});

test('버튼 접근성과 disabled 처리 및 기존 OAuth handler 연결을 유지한다', () => {
  assert.match(buttonSource, /accessibilityRole="button"/);
  assert.match(buttonSource, /accessibilityLabel="카카오로 로그인"/);
  assert.match(buttonSource, /onPress=\{onPress\}/);
  assert.match(buttonSource, /disabled=\{disabled\}/);
  assert.match(loginSource, /<KakaoLoginButton onPress=\{handleKakaoPress\} disabled=\{isSubmitting\} \/>/);
  assert.match(loginSource, /const result = await signInWithKakao\(\)/);
});

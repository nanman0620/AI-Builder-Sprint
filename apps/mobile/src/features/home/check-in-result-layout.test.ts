import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import test from 'node:test';

const homeScreenSource = readFileSync(
  resolve(process.cwd(), 'src/features/home/screens/home-screen.tsx'),
  'utf8',
);
const planListSource = readFileSync(
  resolve(process.cwd(), 'src/features/home/components/check-in-plan-list.tsx'),
  'utf8',
);

test('CHECK_IN_RESULT는 전체 화면 하나만 스크롤하고 CTA까지 접근 가능하다', () => {
  const resultBody = homeScreenSource.slice(
    homeScreenSource.indexOf('function CheckInResultBody'),
    homeScreenSource.indexOf('const styles = StyleSheet.create'),
  );

  assert.match(resultBody, /<ScrollView[\s\S]*contentContainerStyle=\{styles\.resultContent\}/);
  assert.ok(resultBody.indexOf('<CheckInPlanList') < resultBody.indexOf('styles.filledButton'));
});

test('짧은 결과 목록은 고정 높이와 내부 ScrollView·스크롤바를 만들지 않는다', () => {
  assert.doesNotMatch(planListSource, /height:\s*CARD_HEIGHT/);
  assert.doesNotMatch(planListSource, /<ScrollView/);
  assert.doesNotMatch(planListSource, /scrollbarTrack|scrollbarThumb/);
  assert.match(planListSource, /<View style=\{styles\.content\}>/);
});

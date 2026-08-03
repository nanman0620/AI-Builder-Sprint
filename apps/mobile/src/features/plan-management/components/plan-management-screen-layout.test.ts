import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { test } from 'node:test';

const changeConfirmationSource = readFileSync(
  resolve('src/features/plan-management/components/change-confirmation-screen.tsx'),
  'utf8'
);
const collectingSource = readFileSync(
  resolve('src/features/plan-management/components/collecting-screen.tsx'),
  'utf8'
);
const changeInputSource = readFileSync(
  resolve('src/features/plan-management/components/change-input-screen.tsx'),
  'utf8'
);
const finalReviewSource = readFileSync(
  resolve('src/features/plan-management/components/final-review-screen.tsx'),
  'utf8'
);
const planManagementScreenSource = readFileSync(
  resolve('src/features/plan-management/screens/plan-management-screen.tsx'),
  'utf8'
);
const usePlanManagementSource = readFileSync(
  resolve('src/features/plan-management/hooks/use-plan-management.ts'),
  'utf8'
);
const conversationTimelineSource = readFileSync(
  resolve('src/features/plan-management/components/conversation-timeline.tsx'),
  'utf8'
);

function count(source: string, value: string): number {
  return source.split(value).length - 1;
}

test('CHANGE_CONFIRMATION은 timeline 뒤에 선택 버튼 한 세트만 렌더링한다', () => {
  const timelineIndex = changeConfirmationSource.indexOf('<ConversationTimeline entries={timeline} />');
  const optionIndex = changeConfirmationSource.indexOf('prompt.options.map((option)');

  assert.ok(timelineIndex >= 0, 'conversation timeline을 렌더링해야 한다');
  assert.ok(optionIndex > timelineIndex, '예/아니요 버튼은 timeline의 decision prompt 뒤에 렌더링해야 한다');
  assert.equal(count(changeConfirmationSource, 'prompt.options.map((option)'), 1);
  assert.match(changeConfirmationSource, /\{prompt \? <View style=\{styles\.options\}>/);
  assert.doesNotMatch(changeConfirmationSource, /request\.requestItems/);
});

test('대화 화면은 최신 requestItems 상단 목록 대신 timeline을 사용한다', () => {
  for (const source of [collectingSource, changeConfirmationSource, changeInputSource]) {
    assert.match(source, /buildConversationTimeline/);
    assert.match(source, /ConversationTimeline/);
    assert.doesNotMatch(source, /request\.requestItems/);
  }
});

test('FINAL_REVIEW는 제목, 단일 카드 목록, 수정과 모두 등록 action만 렌더링한다', () => {
  assert.match(finalReviewSource, /할 일 및 고정 일정 등록/);
  assert.equal(count(finalReviewSource, 'sortedItems.map((item)'), 1);
  assert.match(finalReviewSource, />수정<\/Text>/);
  assert.match(finalReviewSource, /모두 등록/);

  assert.doesNotMatch(finalReviewSource, /ChatMessageBubble/);
  assert.doesNotMatch(finalReviewSource, /getVisibleConversationMessages/);
  assert.doesNotMatch(finalReviewSource, /MessageInput/);
  assert.doesNotMatch(finalReviewSource, /decisionPrompt/);
  assert.doesNotMatch(finalReviewSource, /sortedMessages/);
  assert.doesNotMatch(finalReviewSource, /LEGACY_CURRENT_REQUEST_ITEM/);
  assert.doesNotMatch(finalReviewSource, /ConversationTimeline/);
});

test('legacy current item은 공용 카드 정책으로 렌더링한다', () => {
  assert.match(conversationTimelineSource, /entry\.type === 'LEGACY_CURRENT_REQUEST_ITEM'/);
  assert.match(conversationTimelineSource, /<RequestItemCard key=\{entry\.id\} item=\{entry\.item\} \/>/);
});

test('질문 대상 안내는 카드가 아니라 별도 assistant 말풍선으로 렌더링한다', () => {
  assert.match(conversationTimelineSource, /entry\.type === 'QUESTION_TARGET_INTRO'/);
  assert.match(
    conversationTimelineSource,
    /entry\.type === 'QUESTION_TARGET_INTRO'[\s\S]*?<ChatMessageBubble[\s\S]*?kind: 'TEXT',[\s\S]*?content: entry\.message/
  );
});

test('서버 screenMode가 CHANGE_INPUT, FINAL_REVIEW, EXECUTING 전용 화면을 선택한다', () => {
  assert.match(
    planManagementScreenSource,
    /case 'CHANGE_INPUT':[\s\S]*?<ChangeInputScreen[\s\S]*?case 'FINAL_REVIEW':[\s\S]*?<FinalReviewScreen[\s\S]*?case 'EXECUTING':[\s\S]*?<ExecutingScreen/
  );
  assert.match(planManagementScreenSource, /onReopen=\{reopenRequest\}/);
  assert.match(planManagementScreenSource, /onExecute=\{executeRequest\}/);
});

test('execute는 FINAL_REVIEW에서만 시작하고 pending action으로 연속 전송을 막는다', () => {
  assert.match(
    usePlanManagementSource,
    /if \(!state\?\.request \|\| state\.screenMode !== 'FINAL_REVIEW'\) return;/
  );
  assert.match(usePlanManagementSource, /if \(!beginAction\(actionKey\)\) return;/);
  assert.match(usePlanManagementSource, /screenMode: 'EXECUTING'/);
  assert.match(usePlanManagementSource, /status: 'EXECUTING'/);
});

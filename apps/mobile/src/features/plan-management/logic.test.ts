// 순수 함수 테스트다. apps/mobile/src/features/bootstrap/route.test.ts와 같은 방식으로
// 로컬 tsc로 CommonJS 컴파일 후 `node --test`로 실행한다.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  applyAcknowledgeResult,
  buildConversationTimeline,
  computeExecutionCompletedResult,
  getVisibleConversationMessages,
  normalizeExecutionStatusResponse,
  normalizePlanManagementState,
  type RawExecutionResult,
} from './logic';
import type {
  AcknowledgeExecutionResultResponse,
  ExecutionStatusResponse,
  PlanManagementState,
  SolarRequest,
  SolarRequestItem,
} from './types';

function makeRequest(overrides: Partial<SolarRequest> = {}): SolarRequest {
  return {
    id: 'request-1',
    purpose: 'NEW_CYCLE',
    status: 'CHANGE_CONFIRMATION',
    messages: [],
    requestItems: [],
    currentQuestion: null,
    quickReplies: [],
    inputPlaceholder: null,
    pendingItemId: null,
    decisionPrompt: {
      message: '추가하거나 수정할 내용이 있나요?',
      options: [
        { value: 'YES', label: '예' },
        { value: 'NO', label: '아니요' },
      ],
    },
    reviewSummary: null,
    execution: null,
    ...overrides,
  };
}

test('pending decision question is shown once with its selection UI source intact', () => {
  const request = makeRequest();
  const messages = getVisibleConversationMessages(request);

  assert.deepEqual(messages.map((message) => message.content), ['추가하거나 수정할 내용이 있나요?']);
  assert.equal(request.decisionPrompt?.options.length, 2);
});

test('failed selection keeps the previous pending question and options available for retry', () => {
  const previousRequest = makeRequest();

  assert.deepEqual(
    getVisibleConversationMessages(previousRequest).map((message) => message.content),
    ['추가하거나 수정할 내용이 있나요?']
  );
  assert.deepEqual(previousRequest.decisionPrompt?.options.map((option) => option.value), [
    'YES',
    'NO',
  ]);
});

for (const [decision, label, status] of [
  ['YES', '예', 'CHANGE_INPUT'],
  ['NO', '아니요', 'FINAL_REVIEW'],
] as const) {
  test(`${decision} response keeps one question and one answer after transition`, () => {
    const request = makeRequest({
      status,
      decisionPrompt: null,
      messages: [
        {
          id: 'question-1',
          role: 'ASSISTANT',
          kind: 'QUESTION',
          content: '추가하거나 수정할 내용이 있나요?',
          sequenceNo: 2,
          createdAt: '',
          metadata: { promptType: 'CHANGE_CONFIRMATION', decisionClientEventId: 'event-1' },
        },
        {
          id: 'answer-1',
          role: 'USER',
          kind: 'DECISION',
          content: label,
          sequenceNo: 3,
          createdAt: '',
          metadata: { decision },
        },
      ],
    });

    assert.equal(request.messages.length, 2);
    assert.deepEqual(
      getVisibleConversationMessages(request).map((message) => message.content),
      decision === 'YES' ? ['추가하거나 수정할 내용이 있나요?', label] : []
    );
    assert.equal(request.decisionPrompt, null);
  });
}

test('완료된 이전 decision pair는 새 CHANGE_CONFIRMATION prompt를 억제하지 않는다', () => {
  const request = makeRequest({
    messages: [
      {
        id: 'question-1',
        role: 'ASSISTANT',
        kind: 'QUESTION',
        content: '추가하거나 수정할 내용이 있나요?',
        sequenceNo: 1,
        createdAt: '',
        metadata: { promptType: 'CHANGE_CONFIRMATION' },
      },
      {
        id: 'answer-1', role: 'USER', kind: 'DECISION', content: '아니요', sequenceNo: 2,
        createdAt: '', metadata: { decision: 'NO' },
      },
    ],
  });

  assert.deepEqual(getVisibleConversationMessages(request).map((message) => message.content), [
    '추가하거나 수정할 내용이 있나요?',
  ]);
});

test('non-decision pending questions remain ordinary history messages', () => {
  const request = makeRequest({
    status: 'COLLECTING',
    decisionPrompt: null,
    messages: [
      {
        id: 'question-2',
        role: 'ASSISTANT',
        kind: 'QUESTION',
        content: '마감일은 언제인가요?',
        sequenceNo: 1,
        createdAt: '',
        metadata: { itemId: 'item-1', field: 'deadlineAt' },
      },
    ],
  });

  assert.deepEqual(getVisibleConversationMessages(request).map((message) => message.content), [
    '마감일은 언제인가요?',
  ]);
});

function snapshot(overrides: Record<string, unknown> = {}) {
  return {
    snapshotId: 'snapshot-1',
    requestItemId: 'item-1',
    itemOrder: 1,
    action: 'CREATE',
    actionLabel: '추가',
    entityType: 'TASK',
    entityLabel: '할 일',
    status: 'INFO_MISSING',
    statusLabel: '정보 부족',
    title: '자료구조 과제',
    summaryText: '정보 부족 · 분량 필요',
    missingFields: ['amount'],
    ...overrides,
  };
}

function makeRequestItem(overrides: Partial<SolarRequestItem> = {}): SolarRequestItem {
  return {
    id: 'item-1',
    itemOrder: 1,
    action: 'CREATE',
    actionLabel: '추가',
    entityType: 'TASK',
    entityLabel: '할 일',
    status: 'READY',
    statusLabel: '준비됨',
    rawLineText: '자료구조 과제',
    title: '자료구조 과제',
    summaryText: '준비됨 · 3문제',
    normalizedPayload: null,
    missingFields: [],
    pendingQuestion: null,
    targetEntityId: null,
    targetSnapshot: null,
    ...overrides,
  };
}

function messageWithSnapshots(
  id: string,
  sequenceNo: number,
  content: string,
  snapshots: unknown[]
) {
  return {
    id,
    role: 'ASSISTANT' as const,
    kind: 'TEXT' as const,
    content,
    sequenceNo,
    createdAt: '',
    metadata: { snapshotVersion: 1, requestItemSnapshots: snapshots },
  };
}

test('timeline은 message 다음에 itemOrder 순 snapshot, 그 뒤 decisionPrompt를 둔다', () => {
  const request = makeRequest({
    messages: [
      {
        id: 'user-1', role: 'USER', kind: 'TEXT', content: '입력', sequenceNo: 1,
        createdAt: '', metadata: {},
      },
      messageWithSnapshots('analysis-1', 2, '분석했어요.', [
        snapshot({ snapshotId: 'snapshot-2', requestItemId: 'item-2', itemOrder: 2 }),
        snapshot(),
      ]),
    ],
  });

  const timeline = buildConversationTimeline(request);
  assert.deepEqual(timeline.map((entry) => entry.type), [
    'MESSAGE', 'MESSAGE', 'REQUEST_ITEM_SNAPSHOT', 'REQUEST_ITEM_SNAPSHOT', 'DECISION_PROMPT',
  ]);
  assert.deepEqual(
    timeline.filter((entry) => entry.type === 'REQUEST_ITEM_SNAPSHOT').map((entry) => entry.snapshot.itemOrder),
    [1, 2]
  );
});

test('timeline은 과거 INFO_MISSING과 다음 READY snapshot을 서로 다른 시점으로 보존한다', () => {
  const oldSnapshot = snapshot();
  const readySnapshot = snapshot({
    snapshotId: 'snapshot-2', status: 'READY', statusLabel: '준비됨',
    summaryText: '준비됨 · 3문제', missingFields: [],
  });
  const request = makeRequest({
    status: 'CHANGE_INPUT',
    decisionPrompt: null,
    messages: [
      messageWithSnapshots('analysis-1', 1, '처음 분석', [oldSnapshot]),
      { id: 'question', role: 'ASSISTANT', kind: 'QUESTION', content: '분량?', sequenceNo: 2, createdAt: '', metadata: { itemId: 'item-1' } },
      { id: 'answer', role: 'USER', kind: 'TEXT', content: '3문제', sequenceNo: 3, createdAt: '', metadata: {} },
      messageWithSnapshots('analysis-2', 4, '준비됐어요.', [readySnapshot]),
    ],
  });

  const timeline = buildConversationTimeline(request);
  const snapshots = timeline
    .filter((entry) => entry.type === 'REQUEST_ITEM_SNAPSHOT')
    .map((entry) => entry.snapshot);
  assert.deepEqual(snapshots.map((entry) => entry.summaryText), [
    '정보 부족 · 분량 필요', '준비됨 · 3문제',
  ]);
  assert.equal((oldSnapshot as { summaryText: string }).summaryText, '정보 부족 · 분량 필요');
});

test('timeline은 같은 snapshotId만 제거하고 같은 item의 다른 snapshotId는 유지한다', () => {
  const repeated = snapshot();
  const request = makeRequest({
    decisionPrompt: null,
    messages: [
      messageWithSnapshots('analysis-1', 1, '20개', [repeated, repeated]),
      messageWithSnapshots('analysis-2', 2, '40개', [snapshot({
        snapshotId: 'snapshot-2', summaryText: '준비됨 · 40개', missingFields: [], status: 'READY',
      })]),
    ],
  });

  const first = buildConversationTimeline(request);
  const second = buildConversationTimeline(request);
  assert.deepEqual(first, second);
  assert.equal(first.filter((entry) => entry.type === 'REQUEST_ITEM_SNAPSHOT').length, 2);
});

test('timeline은 잘못된 snapshot metadata를 무시하고 기존 message를 유지한다', () => {
  const request = makeRequest({
    decisionPrompt: null,
    messages: [messageWithSnapshots('analysis', 1, '분석', [{ snapshotId: 'broken' }])],
  });
  assert.deepEqual(buildConversationTimeline(request).map((entry) => entry.type), ['MESSAGE']);
});

test('이전 완료 decision pair가 있어도 현재 decisionPrompt를 정확히 한 번 합성한다', () => {
  const request = makeRequest({
    messages: [
      {
        id: 'question', role: 'ASSISTANT', kind: 'QUESTION', content: '이전 수정?', sequenceNo: 1,
        createdAt: '', metadata: { promptType: 'CHANGE_CONFIRMATION', decisionClientEventId: 'event-1' },
      },
      {
        id: 'answer', role: 'USER', kind: 'DECISION', content: '아니요', sequenceNo: 2,
        createdAt: '', metadata: { decision: 'NO' },
      },
    ],
  });
  const timeline = buildConversationTimeline(request);
  assert.equal(timeline.filter((entry) => entry.type === 'DECISION_PROMPT').length, 1);
  assert.equal(timeline.filter((entry) => entry.type === 'MESSAGE').length, 0);
});

function completedDecisionPair(sequenceNo: number, decision: 'YES' | 'NO') {
  const eventId = `decision-${sequenceNo}`;
  return [
    {
      id: `question-${sequenceNo}`, role: 'ASSISTANT' as const, kind: 'QUESTION' as const,
      content: '수정하거나 추가할 내용이 있나요?', sequenceNo, createdAt: '',
      metadata: { promptType: 'CHANGE_CONFIRMATION', decisionClientEventId: eventId },
    },
    {
      id: `answer-${sequenceNo}`, role: 'USER' as const, kind: 'DECISION' as const,
      content: decision === 'YES' ? '예' : '아니요', sequenceNo: sequenceNo + 1, createdAt: '',
      metadata: { decision },
    },
  ];
}

test('NO 후 reopen CHANGE_INPUT은 history data를 유지하되 완료 NO pair를 숨긴다', () => {
  const pair = completedDecisionPair(1, 'NO');
  const request = makeRequest({ status: 'CHANGE_INPUT', decisionPrompt: null, messages: pair });
  assert.equal(request.messages.length, 2);
  assert.deepEqual(buildConversationTimeline(request), []);
});

test('YES 직후 CHANGE_INPUT은 마지막 YES pair를 수정 진입 맥락으로 유지한다', () => {
  const request = makeRequest({
    status: 'CHANGE_INPUT', decisionPrompt: null, messages: completedDecisionPair(1, 'YES'),
  });
  assert.deepEqual(
    buildConversationTimeline(request)
      .filter((entry) => entry.type === 'MESSAGE')
      .map((entry) => entry.message.content),
    ['수정하거나 추가할 내용이 있나요?', '예']
  );
});

test('재수정 후 CHANGE_CONFIRMATION은 이전 pair를 숨기고 새 turn과 현재 prompt만 표시한다', () => {
  const request = makeRequest({
    messages: [
      ...completedDecisionPair(1, 'NO'),
      { id: 'new-user', role: 'USER', kind: 'TEXT', content: '새 일정 추가', sequenceNo: 3, createdAt: '', metadata: {} },
      messageWithSnapshots('new-analysis', 4, '추가했어요.', [snapshot({ status: 'READY', statusLabel: '준비됨', missingFields: [] })]),
    ],
  });
  const timeline = buildConversationTimeline(request);
  assert.deepEqual(timeline.map((entry) => entry.type), [
    'MESSAGE', 'MESSAGE', 'REQUEST_ITEM_SNAPSHOT', 'DECISION_PROMPT',
  ]);
  assert.deepEqual(
    timeline.filter((entry) => entry.type === 'MESSAGE').map((entry) => entry.message.content),
    ['새 일정 추가', '추가했어요.']
  );
});

test('여러 confirmation 반복 후에도 완료 pair는 숨기고 일반 대화와 snapshot은 유지한다', () => {
  const request = makeRequest({
    messages: [
      { id: 'initial', role: 'ASSISTANT', kind: 'TEXT', content: '최초 분석', sequenceNo: 1, createdAt: '', metadata: {} },
      ...completedDecisionPair(2, 'YES'),
      { id: 'edit-1', role: 'USER', kind: 'TEXT', content: '첫 수정', sequenceNo: 4, createdAt: '', metadata: {} },
      messageWithSnapshots('analysis-1', 5, '첫 수정 완료', [snapshot()]),
      ...completedDecisionPair(6, 'YES'),
      { id: 'edit-2', role: 'USER', kind: 'TEXT', content: '둘째 수정', sequenceNo: 8, createdAt: '', metadata: {} },
      messageWithSnapshots('analysis-2', 9, '둘째 수정 완료', [snapshot({ snapshotId: 'snapshot-2' })]),
    ],
  });
  const timeline = buildConversationTimeline(request);
  assert.deepEqual(
    timeline.filter((entry) => entry.type === 'MESSAGE').map((entry) => entry.message.content),
    ['최초 분석', '첫 수정', '첫 수정 완료', '둘째 수정', '둘째 수정 완료']
  );
  assert.equal(timeline.filter((entry) => entry.type === 'REQUEST_ITEM_SNAPSHOT').length, 2);
  assert.equal(timeline.filter((entry) => entry.type === 'DECISION_PROMPT').length, 1);
});

for (const status of ['COLLECTING', 'CHANGE_INPUT'] as const) {
  test(`legacy ${status}는 messages 뒤에 최신 requestItems를 한 번만 표시한다`, () => {
    const request = makeRequest({
      status,
      decisionPrompt: null,
      requestItems: [
        makeRequestItem({ id: 'item-2', itemOrder: 2, entityType: 'FIXED_SCHEDULE', entityLabel: '고정 일정' }),
        makeRequestItem(),
      ],
      messages: [{
        id: 'message-1', role: 'USER', kind: 'TEXT', content: '기존 요청', sequenceNo: 1,
        createdAt: '', metadata: {},
      }],
    });

    const first = buildConversationTimeline(request);
    const second = buildConversationTimeline(request);
    assert.deepEqual(first, second);
    assert.deepEqual(first.map((entry) => entry.type), [
      'MESSAGE', 'LEGACY_CURRENT_REQUEST_ITEM', 'LEGACY_CURRENT_REQUEST_ITEM',
    ]);
    assert.deepEqual(
      first.filter((entry) => entry.type === 'LEGACY_CURRENT_REQUEST_ITEM').map((entry) => entry.id),
      [`legacy-current:${request.id}:item-1`, `legacy-current:${request.id}:item-2`]
    );
  });
}

test('legacy CHANGE_CONFIRMATION은 현재 카드 뒤에 decisionPrompt를 둔다', () => {
  const request = makeRequest({ requestItems: [makeRequestItem()] });
  assert.deepEqual(buildConversationTimeline(request).map((entry) => entry.type), [
    'LEGACY_CURRENT_REQUEST_ITEM', 'DECISION_PROMPT',
  ]);
});

test('유효 snapshot이 하나라도 있으면 혼합 history에 legacy fallback을 추가하지 않는다', () => {
  const request = makeRequest({
    requestItems: [makeRequestItem(), makeRequestItem({ id: 'legacy-only', itemOrder: 2 })],
    messages: [
      { id: 'old', role: 'ASSISTANT', kind: 'TEXT', content: '옛 분석', sequenceNo: 1, createdAt: '', metadata: {} },
      messageWithSnapshots('new', 2, '새 분석', [snapshot()]),
    ],
  });
  const timeline = buildConversationTimeline(request);
  assert.equal(timeline.filter((entry) => entry.type === 'REQUEST_ITEM_SNAPSHOT').length, 1);
  assert.equal(timeline.filter((entry) => entry.type === 'LEGACY_CURRENT_REQUEST_ITEM').length, 0);
});

test('malformed snapshot만 있으면 legacy fallback으로 카드를 유실하지 않는다', () => {
  const malformedMetadata = [
    {},
    { snapshotVersion: 2, requestItemSnapshots: [snapshot()] },
    { snapshotVersion: 1, requestItemSnapshots: 'not-an-array' },
    { snapshotVersion: 1, requestItemSnapshots: [{ snapshotId: 'broken' }] },
  ];
  for (const [index, metadata] of malformedMetadata.entries()) {
    const request = makeRequest({
      decisionPrompt: null,
      requestItems: [makeRequestItem()],
      messages: [{
        id: `message-${index}`, role: 'ASSISTANT', kind: 'TEXT', content: '분석',
        sequenceNo: 1, createdAt: '', metadata,
      }],
    });
    assert.equal(
      buildConversationTimeline(request).filter((entry) => entry.type === 'LEGACY_CURRENT_REQUEST_ITEM').length,
      1
    );
  }
});

test('requestItems가 비어 있으면 legacy fallback 영역을 만들지 않는다', () => {
  const request = makeRequest({ decisionPrompt: null, requestItems: [] });
  assert.equal(buildConversationTimeline(request).length, 0);
});

function makeRaw(overrides: Partial<RawExecutionResult> = {}): RawExecutionResult {
  return {
    createdTaskCount: 0,
    updatedTaskCount: 0,
    cancelledTaskCount: 0,
    createdFixedScheduleCount: 0,
    updatedFixedScheduleCount: 0,
    deletedFixedScheduleCount: 0,
    ...overrides,
  };
}

test('computeExecutionCompletedResult: taskCount는 created+updated+cancelled 합', () => {
  const raw = makeRaw({ createdTaskCount: 2, updatedTaskCount: 1, cancelledTaskCount: 1 });
  const result = computeExecutionCompletedResult(raw);
  assert.equal(result.taskCount, 4);
});

test('computeExecutionCompletedResult: fixedScheduleCount는 created+updated+deleted 합', () => {
  const raw = makeRaw({
    createdFixedScheduleCount: 1,
    updatedFixedScheduleCount: 2,
    deletedFixedScheduleCount: 3,
  });
  const result = computeExecutionCompletedResult(raw);
  assert.equal(result.fixedScheduleCount, 6);
});

test('computeExecutionCompletedResult: 전부 0이어도 undefined가 아니라 0', () => {
  const result = computeExecutionCompletedResult(makeRaw());
  assert.equal(result.taskCount, 0);
  assert.equal(result.fixedScheduleCount, 0);
  assert.notEqual(result.taskCount, undefined);
  assert.notEqual(result.fixedScheduleCount, undefined);
});

test('computeExecutionCompletedResult: 서버가 taskCount/fixedScheduleCount를 함께 보내도 무시하고 원본 6개로 다시 계산한다', () => {
  const raw = {
    ...makeRaw({ createdTaskCount: 2, createdFixedScheduleCount: 1 }),
    // 서버 계약에 없는 값이 섞여 들어와도(예: 오래된 캐시) 그대로 신뢰하지 않는다.
    taskCount: 999,
    fixedScheduleCount: 999,
  } as RawExecutionResult;
  const result = computeExecutionCompletedResult(raw);
  assert.equal(result.taskCount, 2);
  assert.equal(result.fixedScheduleCount, 1);
});

function makePlanManagementState(): PlanManagementState {
  return {
    screenMode: 'EXECUTION_SUCCESS',
    activeCycle: null,
    request: {
      id: 'req-1',
      purpose: 'NEW_CYCLE',
      status: 'COMPLETED',
      messages: [],
      requestItems: [],
      currentQuestion: null,
      quickReplies: [],
      inputPlaceholder: null,
      pendingItemId: null,
      decisionPrompt: null,
      reviewSummary: null,
      execution: {
        executionStartedAt: '2026-07-29T14:20:00+09:00',
        executionAttemptCount: 1,
        executedAt: '2026-07-29T14:20:05+09:00',
        executionResult: makeRaw({ createdTaskCount: 2, createdFixedScheduleCount: 1 }) as never,
        error: null,
      },
    },
  } as PlanManagementState;
}

test('normalizePlanManagementState: execution.executionResult의 count를 원본 6개로 채운다', () => {
  const state = makePlanManagementState();
  const normalized = normalizePlanManagementState(state);
  assert.ok(normalized.request);
  const result = normalized.request!.execution!.executionResult!;
  assert.equal(result.taskCount, 2);
  assert.equal(result.fixedScheduleCount, 1);
});

test('normalizePlanManagementState: request가 없으면 그대로 반환한다', () => {
  const state: PlanManagementState = {
    screenMode: 'NEW_CYCLE_ENTRY',
    activeCycle: null,
    request: null,
  };
  assert.deepEqual(normalizePlanManagementState(state), state);
});

test('normalizeExecutionStatusResponse: COMPLETED면 executionResult의 count를 다시 계산한다', () => {
  const response = {
    requestId: 'req-1',
    purpose: 'NEW_CYCLE',
    status: 'COMPLETED',
    screenMode: 'EXECUTION_SUCCESS',
    executionStartedAt: '2026-07-29T14:20:00+09:00',
    executionAttemptCount: 1,
    executedAt: '2026-07-29T14:20:05+09:00',
    executionResult: makeRaw({ updatedTaskCount: 3 }) as never,
    error: null,
  } as ExecutionStatusResponse;
  const normalized = normalizeExecutionStatusResponse(response);
  assert.equal((normalized as { executionResult: { taskCount: number } }).executionResult.taskCount, 3);
});

test('normalizeExecutionStatusResponse: EXECUTING이면 그대로 반환한다(executionResult=null)', () => {
  const response: ExecutionStatusResponse = {
    requestId: 'req-1',
    purpose: 'NEW_CYCLE',
    status: 'EXECUTING',
    screenMode: 'EXECUTING',
    executionStartedAt: '2026-07-29T14:20:00+09:00',
    executionAttemptCount: 1,
    executedAt: null,
    executionResult: null,
    error: null,
  };
  assert.deepEqual(normalizeExecutionStatusResponse(response), response);
});

test('applyAcknowledgeResult: 성공 응답을 받으면 request를 비우고 서버가 정한 다음 화면으로 전환한다', () => {
  const state = makePlanManagementState();
  const response: AcknowledgeExecutionResultResponse = {
    requestId: 'req-1',
    resultAcknowledgedAt: '2026-07-29T14:21:00+09:00',
    nextPlanManagementScreenMode: 'ACTIVE_CYCLE_ENTRY',
  };
  const next = applyAcknowledgeResult(state, response);
  assert.deepEqual(next, {
    screenMode: 'ACTIVE_CYCLE_ENTRY',
    activeCycle: null,
    request: null,
  });
});

test('applyAcknowledgeResult: requestId가 다르면(경합) 상태를 바꾸지 않는다', () => {
  const state = makePlanManagementState();
  const response: AcknowledgeExecutionResultResponse = {
    requestId: 'other-request',
    resultAcknowledgedAt: '2026-07-29T14:21:00+09:00',
    nextPlanManagementScreenMode: 'ACTIVE_CYCLE_ENTRY',
  };
  assert.deepEqual(applyAcknowledgeResult(state, response), state);
});

test('applyAcknowledgeResult: request가 이미 없으면 상태를 바꾸지 않는다', () => {
  const state: PlanManagementState = {
    screenMode: 'NEW_CYCLE_ENTRY',
    activeCycle: null,
    request: null,
  };
  const response: AcknowledgeExecutionResultResponse = {
    requestId: 'req-1',
    resultAcknowledgedAt: '2026-07-29T14:21:00+09:00',
    nextPlanManagementScreenMode: 'ACTIVE_CYCLE_ENTRY',
  };
  assert.deepEqual(applyAcknowledgeResult(state, response), state);
});

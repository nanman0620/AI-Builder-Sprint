// 순수 함수 테스트다. apps/mobile/src/features/bootstrap/route.test.ts와 같은 방식으로
// 로컬 tsc로 CommonJS 컴파일 후 `node --test`로 실행한다.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  applyAcknowledgeResult,
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

    assert.deepEqual(
      getVisibleConversationMessages(request).map((message) => message.content),
      ['추가하거나 수정할 내용이 있나요?', label]
    );
    assert.equal(request.decisionPrompt, null);
  });
}

test('persisted prompt identifier prevents duplicate rendering after a refetch', () => {
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
    ],
  });

  assert.equal(getVisibleConversationMessages(request).length, 1);
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

// 계획관리 상태 계산용 순수 함수 모음. RN 의존성이 없어
// apps/mobile/src/features/bootstrap/route.ts와 같은 방식으로 `node --test`로 검증한다.
import type {
  AcknowledgeExecutionResultResponse,
  ExecutionCompletedResult,
  ExecutionSnapshot,
  ExecutionStatusResponse,
  PlanManagementState,
  SolarRequest,
} from './types';

const CHANGE_CONFIRMATION_PROMPT_TYPE = 'CHANGE_CONFIRMATION';

export function getVisibleConversationMessages(request: SolarRequest) {
  const messages = [...request.messages].sort((a, b) => a.sequenceNo - b.sequenceNo);
  const prompt = request.decisionPrompt;
  if (!prompt) {
    return messages;
  }

  const promptAlreadyPersisted = messages.some(
    (message) =>
      message.role === 'ASSISTANT' &&
      message.kind === 'QUESTION' &&
      message.metadata.promptType === CHANGE_CONFIRMATION_PROMPT_TYPE
  );
  if (promptAlreadyPersisted) {
    return messages;
  }

  const lastSequenceNo = messages.at(-1)?.sequenceNo ?? 0;
  return [
    ...messages,
    {
      id: `decision-prompt:${request.id}`,
      role: 'ASSISTANT' as const,
      kind: 'QUESTION' as const,
      content: prompt.message,
      sequenceNo: lastSequenceNo + 1,
      createdAt: '',
      metadata: { promptType: CHANGE_CONFIRMATION_PROMPT_TYPE },
    },
  ];
}

// 서버 execution_result에 실제로 저장되는 6개 원본 key.
// docs/database/이음_MVP_최종_DB_구조.pdf의 execution_result 절: taskCount·fixedScheduleCount는
// DB에 저장하지 않고 이 6개로부터 매번 계산한다.
export type RawExecutionResult = {
  createdTaskCount: number;
  updatedTaskCount: number;
  cancelledTaskCount: number;
  createdFixedScheduleCount: number;
  updatedFixedScheduleCount: number;
  deletedFixedScheduleCount: number;
};

// taskCount = createdTaskCount + updatedTaskCount + cancelledTaskCount
// fixedScheduleCount = createdFixedScheduleCount + updatedFixedScheduleCount + deletedFixedScheduleCount
// (DB 구조 문서 execution_result 절의 공식.) 서버가 taskCount/fixedScheduleCount를 함께 보내더라도
// 신뢰하지 않고 이 6개 원본 key로 항상 다시 계산한다 — 0건이어도 undefined가 아니라 0으로 보인다.
export function computeExecutionCompletedResult(raw: RawExecutionResult): ExecutionCompletedResult {
  return {
    createdTaskCount: raw.createdTaskCount,
    updatedTaskCount: raw.updatedTaskCount,
    cancelledTaskCount: raw.cancelledTaskCount,
    createdFixedScheduleCount: raw.createdFixedScheduleCount,
    updatedFixedScheduleCount: raw.updatedFixedScheduleCount,
    deletedFixedScheduleCount: raw.deletedFixedScheduleCount,
    taskCount: raw.createdTaskCount + raw.updatedTaskCount + raw.cancelledTaskCount,
    fixedScheduleCount:
      raw.createdFixedScheduleCount + raw.updatedFixedScheduleCount + raw.deletedFixedScheduleCount,
  };
}

function normalizeExecutionSnapshot(execution: ExecutionSnapshot | null): ExecutionSnapshot | null {
  if (!execution || !execution.executionResult) {
    return execution;
  }
  return {
    ...execution,
    executionResult: computeExecutionCompletedResult(
      execution.executionResult as unknown as RawExecutionResult
    ),
  };
}

// GET /plan-management/state, GET /solar/requests/{id}, POST(메시지·결정·재오픈) 응답 전부가
// 이 PlanManagementState 구조를 공유하므로, api 계층에서 이 함수 하나로 정규화한다.
export function normalizePlanManagementState(state: PlanManagementState): PlanManagementState {
  if (!state.request) {
    return state;
  }
  return {
    ...state,
    request: {
      ...state.request,
      execution: normalizeExecutionSnapshot(state.request.execution),
    },
  } as PlanManagementState;
}

// GET /solar/requests/{id}/execution 응답 정규화. COMPLETED가 아니면 executionResult가 null이라
// 그대로 반환한다.
export function normalizeExecutionStatusResponse(
  response: ExecutionStatusResponse
): ExecutionStatusResponse {
  if (response.status !== 'COMPLETED') {
    return response;
  }
  return {
    ...response,
    executionResult: computeExecutionCompletedResult(
      response.executionResult as unknown as RawExecutionResult
    ),
  };
}

// POST acknowledge-result 성공 응답을 로컬 PlanManagementState에 즉시 반영하는 순수 함수.
// 서버가 이미 result_acknowledged_at을 저장하고 다음 화면 모드를 계산해 돌려주므로, 다음 탭
// 재포커스(GET /plan-management/state) 없이도 화면이 곧바로 NEW_CYCLE_ENTRY/ACTIVE_CYCLE_ENTRY로
// 전환된다 — EXECUTION_SUCCESS가 재포커스 타이밍에 따라 반복 노출되는 것을 막는다.
export function applyAcknowledgeResult(
  previous: PlanManagementState,
  response: AcknowledgeExecutionResultResponse
): PlanManagementState {
  if (!previous.request || previous.request.id !== response.requestId) {
    return previous;
  }
  return {
    screenMode: response.nextPlanManagementScreenMode,
    activeCycle: previous.activeCycle,
    request: null,
  };
}

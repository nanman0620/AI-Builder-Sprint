// 계획관리 상태 계산용 순수 함수 모음. RN 의존성이 없어
// apps/mobile/src/features/bootstrap/route.ts와 같은 방식으로 `node --test`로 검증한다.
import type {
  AcknowledgeExecutionResultResponse,
  ExecutionCompletedResult,
  ExecutionSnapshot,
  ExecutionStatusResponse,
  PlanManagementState,
  ConversationTimelineEntry,
  RequestItemSnapshot,
  SolarRequest,
} from './types';

const CHANGE_CONFIRMATION_PROMPT_TYPE = 'CHANGE_CONFIRMATION';

export function getVisibleConversationMessages(request: SolarRequest) {
  const messages = getMessagesForCurrentConfirmationFlow(request);
  const prompt = request.decisionPrompt;
  if (!prompt) {
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

function getMessagesForCurrentConfirmationFlow(request: SolarRequest) {
  const messages = [...request.messages].sort(
    (a, b) => a.sequenceNo - b.sequenceNo || a.id.localeCompare(b.id)
  );
  const completedPairs: {
    questionId: string;
    answerId: string;
    keepInChangeInput: boolean;
  }[] = [];

  for (let index = 0; index < messages.length - 1; index += 1) {
    const question = messages[index];
    const answer = messages[index + 1];
    if (
      question.role !== 'ASSISTANT' ||
      question.kind !== 'QUESTION' ||
      question.metadata.promptType !== CHANGE_CONFIRMATION_PROMPT_TYPE ||
      answer.role !== 'USER' ||
      answer.kind !== 'DECISION' ||
      answer.sequenceNo !== question.sequenceNo + 1
    ) {
      continue;
    }
    completedPairs.push({
      questionId: question.id,
      answerId: answer.id,
      keepInChangeInput:
        request.status === 'CHANGE_INPUT' &&
        answer.metadata.decision === 'YES' &&
        index + 1 === messages.length - 1,
    });
    index += 1;
  }

  const hiddenIds = new Set(
    completedPairs
      .filter((pair) => !pair.keepInChangeInput)
      .flatMap((pair) => [pair.questionId, pair.answerId])
  );
  return messages.filter((message) => !hiddenIds.has(message.id));
}

const ITEM_ACTIONS = new Set(['CREATE', 'UPDATE', 'DELETE']);
const ENTITY_TYPES = new Set(['TASK', 'FIXED_SCHEDULE']);
const ITEM_STATUSES = new Set(['INFO_MISSING', 'READY', 'EXECUTED']);

function parseRequestItemSnapshot(value: unknown): RequestItemSnapshot | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  const stringFields = [
    'snapshotId',
    'requestItemId',
    'actionLabel',
    'entityLabel',
    'statusLabel',
    'title',
    'summaryText',
  ] as const;
  if (stringFields.some((field) => typeof raw[field] !== 'string' || !raw[field])) return null;
  if (!Number.isInteger(raw.itemOrder) || (raw.itemOrder as number) < 1) return null;
  if (!ITEM_ACTIONS.has(String(raw.action))) return null;
  if (!ENTITY_TYPES.has(String(raw.entityType))) return null;
  if (!ITEM_STATUSES.has(String(raw.status))) return null;
  if (!Array.isArray(raw.missingFields) || raw.missingFields.some((field) => typeof field !== 'string')) {
    return null;
  }
  return raw as unknown as RequestItemSnapshot;
}

function getMessageSnapshots(message: SolarRequest['messages'][number]): RequestItemSnapshot[] {
  if (message.metadata.snapshotVersion !== 1 || !Array.isArray(message.metadata.requestItemSnapshots)) {
    return [];
  }
  return message.metadata.requestItemSnapshots
    .map(parseRequestItemSnapshot)
    .filter((snapshot): snapshot is RequestItemSnapshot => snapshot !== null)
    .sort((a, b) => a.itemOrder - b.itemOrder || a.snapshotId.localeCompare(b.snapshotId));
}

function getQuestionTarget(message: SolarRequest['messages'][number]) {
  const itemId = message.metadata.itemId;
  const field = message.metadata.field;
  if (
    message.role !== 'ASSISTANT' ||
    message.kind !== 'QUESTION' ||
    message.metadata.promptType === CHANGE_CONFIRMATION_PROMPT_TYPE ||
    message.metadata.followUpType === 'CHANGE_DETAILS' ||
    message.metadata.unresolved === true ||
    typeof itemId !== 'string' ||
    !itemId.trim() ||
    typeof field !== 'string' ||
    !field.trim()
  ) {
    return null;
  }
  return { itemId: itemId.trim(), field: field.trim() };
}

function findLegacyActiveQuestionId(messages: SolarRequest['messages']): string | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (!getQuestionTarget(message)) continue;
    const hasLaterUserAnswer = messages
      .slice(index + 1)
      .some((laterMessage) => laterMessage.role === 'USER');
    if (!hasLaterUserAnswer) return message.id;
  }
  return null;
}

export function buildConversationTimeline(request: SolarRequest): ConversationTimelineEntry[] {
  const messages = getMessagesForCurrentConfirmationFlow(request);
  const entries: ConversationTimelineEntry[] = [];
  const seenSnapshotIds = new Set<string>();
  const latestSnapshotsByItemId = new Map<string, RequestItemSnapshot>();
  const messageSnapshots = new Map(
    messages.map((message) => [message.id, getMessageSnapshots(message)])
  );
  const hasValidSnapshots = [...messageSnapshots.values()].some((snapshots) => snapshots.length > 0);
  const legacyItems = !hasValidSnapshots
    ? [...request.requestItems].sort(
        (a, b) => a.itemOrder - b.itemOrder || a.id.localeCompare(b.id)
      )
    : [];
  const legacyItemsById = new Map(legacyItems.map((item) => [item.id, item]));
  const legacyActiveQuestionId = findLegacyActiveQuestionId(messages);
  const nextEligibleQuestionItemIdAfterIndex: (string | null)[] = Array(messages.length).fill(null);
  let nextEligibleQuestionItemId: string | null = null;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    nextEligibleQuestionItemIdAfterIndex[index] = nextEligibleQuestionItemId;
    const target = getQuestionTarget(messages[index]);
    if (target) nextEligibleQuestionItemId = target.itemId;
  }
  let legacyItemsAdded = false;
  let activeQuestionSessionItemId: string | null = null;

  const addLegacyItems = () => {
    if (legacyItemsAdded) return;
    for (const item of legacyItems) {
      entries.push({
        type: 'LEGACY_CURRENT_REQUEST_ITEM',
        id: `legacy-current:${request.id}:${item.id}`,
        item,
      });
    }
    legacyItemsAdded = true;
  };

  for (const [messageIndex, message] of messages.entries()) {
    const target = getQuestionTarget(message);
    if (!target) {
      entries.push({ type: 'MESSAGE', id: `message:${message.id}`, message });
    }
    for (const snapshot of messageSnapshots.get(message.id) ?? []) {
      if (seenSnapshotIds.has(snapshot.snapshotId)) continue;
      seenSnapshotIds.add(snapshot.snapshotId);
      latestSnapshotsByItemId.set(snapshot.requestItemId, snapshot);
      const isIntermediateSnapshot =
        snapshot.status === 'INFO_MISSING' &&
        activeQuestionSessionItemId === snapshot.requestItemId &&
        nextEligibleQuestionItemIdAfterIndex[messageIndex] === snapshot.requestItemId;
      if (!isIntermediateSnapshot) {
        entries.push({
          type: 'REQUEST_ITEM_SNAPSHOT',
          id: `snapshot:${snapshot.snapshotId}`,
          snapshot,
        });
      }
      if (
        snapshot.status === 'READY' &&
        activeQuestionSessionItemId === snapshot.requestItemId
      ) {
        activeQuestionSessionItemId = null;
      }
    }
    if (target) {
      if (message.id === legacyActiveQuestionId) addLegacyItems();
      const snapshotTitle = latestSnapshotsByItemId.get(target.itemId)?.title;
      const legacyTitle = !hasValidSnapshots ? legacyItemsById.get(target.itemId)?.title : undefined;
      const title = snapshotTitle ?? legacyTitle;
      const startsQuestionSession = activeQuestionSessionItemId !== target.itemId;
      if (startsQuestionSession && title) {
        entries.push({
          type: 'QUESTION_TARGET_INTRO',
          id: `question-target-intro:${message.id}`,
          requestItemId: target.itemId,
          title,
          message: `${title}에 대해 질문할게요.`,
        });
      }
      entries.push({ type: 'MESSAGE', id: `message:${message.id}`, message });
      activeQuestionSessionItemId = target.itemId;
    }
  }

  addLegacyItems();

  if (request.decisionPrompt) {
    entries.push({
      type: 'DECISION_PROMPT',
      id: `decision-prompt:${request.id}`,
      message: request.decisionPrompt.message,
    });
  }
  return entries;
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

export type ScreenMode =
  | 'NEW_CYCLE_ENTRY'
  | 'ACTIVE_CYCLE_ENTRY'
  | 'COLLECTING'
  | 'CHANGE_CONFIRMATION'
  | 'CHANGE_INPUT'
  | 'FINAL_REVIEW'
  | 'EXECUTING'
  | 'EXECUTION_SUCCESS'
  | 'EXECUTION_FAILED';

export type SolarRequestStatus =
  | 'COLLECTING'
  | 'CHANGE_CONFIRMATION'
  | 'CHANGE_INPUT'
  | 'FINAL_REVIEW'
  | 'EXECUTING'
  | 'COMPLETED'
  | 'FAILED';

export type RequestPurpose = 'NEW_CYCLE' | 'ACTIVE_CYCLE';
export type ExecutionStatus = 'EXECUTING' | 'COMPLETED' | 'FAILED';

export type ExecutionStartResponse = {
  requestId: string;
  status: 'EXECUTING';
  screenMode: 'EXECUTING';
  executionStartedAt: string;
  executionAttemptCount: number;
};

export type ExecutionCompletedResult = {
  createdTaskCount: number;
  updatedTaskCount: number;
  cancelledTaskCount: number;
  createdFixedScheduleCount: number;
  updatedFixedScheduleCount: number;
  deletedFixedScheduleCount: number;
  taskCount: number;
  fixedScheduleCount: number;
};

export type ExecutionFailureError = {
  code: 'PLAN_EXECUTION_FAILED';
  message: string;
  retryable: boolean;
};

// GET /plan-management/state의 request.execution 중첩 구조. request.status와
// 최상위 screenMode는 이미 바깥 필드에 있으므로 GET /execution DTO와 구분한다.
export type ExecutionSnapshot = {
  executionStartedAt: string | null;
  executionAttemptCount: number;
  executedAt: string | null;
  executionResult: ExecutionCompletedResult | null;
  error: ExecutionFailureError | null;
};

type ExecutionStatusBase = {
  requestId: string;
  purpose: RequestPurpose;
  executionStartedAt: string;
  executionAttemptCount: number;
};

export type ExecutionStatusResponse =
  | (ExecutionStatusBase & {
      status: 'EXECUTING';
      screenMode: 'EXECUTING';
      executedAt: null;
      executionResult: null;
      error: null;
    })
  | (ExecutionStatusBase & {
      status: 'COMPLETED';
      screenMode: 'EXECUTION_SUCCESS';
      executedAt: string;
      executionResult: ExecutionCompletedResult;
      error: null;
    })
  | (ExecutionStatusBase & {
      status: 'FAILED';
      screenMode: 'EXECUTION_FAILED';
      executedAt: null;
      executionResult: null;
      error: ExecutionFailureError;
    });

export type AcknowledgeExecutionResultResponse = {
  requestId: string;
  resultAcknowledgedAt: string;
  nextPlanManagementScreenMode: 'NEW_CYCLE_ENTRY' | 'ACTIVE_CYCLE_ENTRY';
};

export type MessageRole = 'USER' | 'ASSISTANT';
export type MessageKind = 'TEXT' | 'QUESTION' | 'ERROR' | 'DECISION';

export type ChatMessage = {
  id: string;
  role: MessageRole;
  kind: MessageKind;
  content: string;
  sequenceNo: number;
  createdAt: string;
};

export type ItemAction = 'CREATE' | 'UPDATE' | 'DELETE';
export type ItemEntityType = 'TASK' | 'FIXED_SCHEDULE';
export type ItemStatus = 'INFO_MISSING' | 'READY' | 'EXECUTED';

export type EstimateSource = 'USER' | 'AI_ESTIMATED';
export type AmountSource = 'USER' | 'AI_ESTIMATED' | 'UNKNOWN';

export type TaskNormalizedPayload = {
  title: string;
  deadlineAt: string | null;
  estimatedMinutes: number | null;
  estimatedMinutesSource: EstimateSource | null;
  remainingMinutes: number | null;
  amountText: string | null;
  amountSource: AmountSource | null;
};

export type FixedScheduleNormalizedPayload = {
  title: string;
  startAt: string | null;
  endAt: string | null;
};

// API 원본 필드명(normalizedPayload)을 그대로 쓴다. payload로 임의 축약하지 않는다.
export type SolarRequestItem = {
  id: string;
  itemOrder: number;
  action: ItemAction;
  actionLabel: string;
  entityType: ItemEntityType;
  entityLabel: string;
  status: ItemStatus;
  statusLabel: string;
  rawLineText: string;
  title: string;
  summaryText: string;
  normalizedPayload: TaskNormalizedPayload | FixedScheduleNormalizedPayload | null;
  missingFields: string[];
  pendingQuestion: string | null;
  // 수정·삭제 대상 기존 엔티티 id(CREATE면 null)와 그 스냅숏. 스냅숏 내부 구조는
  // 이번 FE-03 범위(FINAL_REVIEW 등)에서 다루지 않으므로 임의로 세부 필드를 정의하지 않는다.
  targetEntityId: string | null;
  targetSnapshot: unknown;
};

export type QuickReply = {
  value: string;
  label: string;
};

// ACTIVE_CYCLE_ENTRY(FE-03 범위)를 포함해 활성 PlanningCycle이 있는 모든 화면에서 쓰인다.
export type ActiveCycle = {
  id: string;
  startDate: string;
  endDate: string;
  status: string;
  activatedAt?: string;
  endedAt?: string | null;
};

export type DecisionOption = {
  value: 'YES' | 'NO';
  label: string;
};

// CHANGE_CONFIRMATION 전용(FE-03 범위 밖)이라 아직 렌더링하지는 않지만,
// 타입은 명세가 확정한 구조를 그대로 선언해 둔다.
export type DecisionPrompt = {
  message: string;
  options: DecisionOption[];
};

// GET /plan-management/state와 GET /solar/requests/{requestId}가 공통으로 반환하는 전체 구조.
// screenMode가 NEW_CYCLE_ENTRY/ACTIVE_CYCLE_ENTRY이면 request는 항상 null이다.
// activeCycle은 NEW_CYCLE_ENTRY이거나 아직 cycle이 생기지 않은 NEW_CYCLE 요청 진행 중이면 null이다.
export type PlanManagementState =
  | { screenMode: 'NEW_CYCLE_ENTRY'; activeCycle: ActiveCycle | null; request: null }
  | { screenMode: 'ACTIVE_CYCLE_ENTRY'; activeCycle: ActiveCycle | null; request: null }
  | {
      screenMode: Exclude<ScreenMode, 'NEW_CYCLE_ENTRY' | 'ACTIVE_CYCLE_ENTRY'>;
      activeCycle: ActiveCycle | null;
      request: SolarRequest;
    };

export type SolarRequest = {
  id: string;
  purpose: RequestPurpose;
  status: SolarRequestStatus;
  messages: ChatMessage[];
  requestItems: SolarRequestItem[];
  currentQuestion: string | null;
  quickReplies: QuickReply[];
  inputPlaceholder: string | null;
  pendingItemId: string | null;
  // CHANGE_CONFIRMATION 전용. 그 외 상태에서는 null.
  decisionPrompt: DecisionPrompt | null;
  // FINAL_REVIEW 전용 요약은 최종 API 명세가 내부 구조를 정의하지 않는다.
  reviewSummary: unknown;
  execution: ExecutionSnapshot | null;
};

// docs/api/이음_MVP_최종_API_명세서.pdf 5-1 "GET /bootstrap" 응답 계약.
// 온보딩 전에는 activeCycle·planManagement·home이 null일 수 있다.

export type PlanCycleStatus = 'ACTIVE' | 'ENDED';

export type BootstrapActiveCycle = {
  id: string;
  startDate: string;
  endDate: string;
  status: PlanCycleStatus;
  activatedAt: string;
  endedAt: string | null;
};

export type PlanManagementScreenMode =
  | 'NEW_CYCLE_ENTRY'
  | 'ACTIVE_CYCLE_ENTRY'
  | 'COLLECTING'
  | 'CHANGE_CONFIRMATION'
  | 'CHANGE_INPUT'
  | 'FINAL_REVIEW'
  | 'EXECUTING'
  | 'EXECUTION_SUCCESS'
  | 'EXECUTION_FAILED';

// solar_requests의 messages/requestItems/decisionPrompt 등 세부 필드는 계획관리 상태 머신을 구현하는
// FE-03~05의 DTO 소유 영역이다. bootstrap은 request 유무와 화면 판정에만 쓰이므로 세부 계약을 다시 정의하지 않는다.
export type BootstrapPlanManagementRequest = Record<string, unknown>;

export type BootstrapPlanManagement = {
  screenMode: PlanManagementScreenMode;
  activeCycle: BootstrapActiveCycle | null;
  request: BootstrapPlanManagementRequest | null;
};

export type PlanPeriod = 'MORNING' | 'AFTERNOON' | 'EVENING';

// DEADLINE_WARNING은 homeMode 값이 아니라 blockingNotice.type이다(API 명세서 9-1 GET /home/current,
// 화면 흐름 PDF 5-5절). blockingNotice=DEADLINE_WARNING이어도 homeMode는 그 아래 실제 상태(예: IN_PROGRESS)를
// 그대로 유지한 채 내려온다. FE-06 조사 중 발견한 타입 불일치를 이번에 바로잡는다.
export type HomeMode = 'NO_ACTIVE_CYCLE' | 'NO_PLANS' | 'IN_PROGRESS' | 'FINALIZING' | 'CHECK_IN_RESULT';

// GET /bootstrap과 GET /home/current가 공통으로 쓰는 홈 하위 구조. 두 endpoint 모두 이 타입들을
// 그대로 참조하며 중복 정의하지 않는다(홈 전용 응답 envelope인 HomeCurrentResponse만
// src/features/home/types.ts 소유 — finalizing·checkInResult를 포함한 필드 타입은 이 파일 소유).
export type HomeProgress = {
  checkedCount: number;
  totalCount: number;
  percentage: number;
};

// 현재 분기 PlanBlock 한 행. status는 정산 전 PLANNED/CHECKED만 존재한다(COMPLETED/NOT_DONE은
// 정산 후 CheckInResult.completedPlans/notDonePlans에서만 나타난다).
export type HomePlanBlock = {
  id: string;
  taskId: string;
  planDate: string;
  period: PlanPeriod;
  allocatedMinutes: number;
  allocatedAmountText: string | null;
  displayTitle: string;
  displayOrder: number;
  status: 'PLANNED' | 'CHECKED';
  checkedAt: string | null;
};

export type DeadlineWarningItem = {
  taskId: string;
  title: string;
  deadlineAt: string;
  requiredMinutes: number;
  availableMinutes: number;
  shortageMinutes: number;
};

export type HomeBlockingNotice = {
  type: 'DEADLINE_WARNING';
  items: DeadlineWarningItem[];
};

// homeMode=FINALIZING일 때만 채워진다. bootstrap.home과 GET /home/current 모두 서버가 같은
// to_home_current_response 계산 결과를 그대로 내려주므로(BE-11), 두 응답이 공통으로 쓰는 이 타입도
// bootstrap/types.ts에 둔다. home/types.ts는 이 타입을 재수출만 한다(순환 참조 금지, 위 43행 주석 참고).
export type FinalizingInfo = {
  checkInId: string;
  checkDate: string;
  period: PlanPeriod;
  finalizationStartedAt: string;
};

export type CheckInPlanStatus = 'COMPLETED' | 'NOT_DONE';

// completedPlans/notDonePlans 항목. 현재 분기 PlanBlock(HomePlanBlock)과 달리 정산 후 결과 표시용
// 축약 필드만 내려온다(displayOrder 등 정렬 정보 없음).
export type CheckInPlanBlockSummary = {
  id: string;
  displayTitle: string;
  status: CheckInPlanStatus;
};

// homeMode=CHECK_IN_RESULT일 때만 채워진다. FinalizingInfo와 같은 이유로 여기 둔다.
export type CheckInResult = {
  id: string;
  checkDate: string;
  period: PlanPeriod;
  totalPlanCount: number;
  completedPlanCount: number;
  notDonePlanCount: number;
  score: number;
  replanUnplacedMinutes: number;
  finalizedAt: string;
  cycleEnded: boolean;
  completedPlans: CheckInPlanBlockSummary[];
  notDonePlans: CheckInPlanBlockSummary[];
};

// bootstrap.data.home은 서버가 GET /home/current와 동일한 HomeCurrentOut 계산 결과를 그대로
// 내려주므로(BE-11 app/schemas/bootstrap.py의 to_home_current_response 재사용), finalizing·
// checkInResult도 GET /home/current와 똑같이 포함된다 — GET /home/current 전용이 아니다.
export type BootstrapHome = {
  logicalDate: string;
  period: PlanPeriod;
  homeMode: HomeMode;
  blockingNotice: HomeBlockingNotice | null;
  activeCycle: BootstrapActiveCycle | null;
  progress: HomeProgress | null;
  planBlocks: HomePlanBlock[];
  finalizing: FinalizingInfo | null;
  checkInResult: CheckInResult | null;
};

export type BootstrapProfile = {
  id: string;
  email: string;
  nickname: string | null;
  onboardingCompleted: boolean;
};

// initialScreen은 서버가 계산해 내려주는 화면 판정 결과 문자열이다. 프론트는 이 값을 그대로 분기에 쓰고
// activeRequest.status 등으로 다시 계산하지 않는다. 계약상 유효한 값은 route.ts의 초기 화면 우선순위표를 따르되,
// 여기서는 string으로 두고 route.ts가 알려진 값인지 런타임에 검증해 알 수 없는 값을 조용히 신뢰하지 않는다.
export type BootstrapResponse = {
  serverTime: string;
  profile: BootstrapProfile;
  initialScreen: string;
  activeCycle: BootstrapActiveCycle | null;
  planManagement: BootstrapPlanManagement | null;
  home: BootstrapHome | null;
};

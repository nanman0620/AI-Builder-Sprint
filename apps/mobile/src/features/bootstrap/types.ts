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

export type HomeMode =
  | 'NO_ACTIVE_CYCLE'
  | 'NO_PLANS'
  | 'IN_PROGRESS'
  | 'FINALIZING'
  | 'CHECK_IN_RESULT'
  | 'DEADLINE_WARNING';

// blockingNotice·progress·planBlocks 항목의 세부 필드는 홈 6개 상태 UI를 구현하는 FE-06의 소유 영역이다.
export type BootstrapHomeBlockingNotice = Record<string, unknown>;
export type BootstrapHomeProgress = Record<string, unknown>;
export type BootstrapHomePlanBlock = Record<string, unknown>;

export type BootstrapHome = {
  logicalDate: string;
  period: PlanPeriod;
  homeMode: HomeMode;
  blockingNotice: BootstrapHomeBlockingNotice | null;
  activeCycle: BootstrapActiveCycle | null;
  progress: BootstrapHomeProgress | null;
  planBlocks: BootstrapHomePlanBlock[];
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

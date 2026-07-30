// docs/api/이음_MVP_최종_API_명세서.pdf 9~10절 "GET /home/current" 및 홈 mutation 4개 계약.
// HomeMode·HomeProgress·HomePlanBlock·DeadlineWarningItem·HomeBlockingNotice는
// bootstrap과 home이 공통으로 쓰는 원본 타입이라 src/features/bootstrap/types.ts에 두고 여기서 재수출만 한다.
// bootstrap/types.ts는 이 파일을 import하지 않는다(순환 참조 금지).
import type {
  BootstrapActiveCycle,
  DeadlineWarningItem,
  HomeBlockingNotice,
  HomeMode,
  HomePlanBlock,
  HomeProgress,
  PlanPeriod,
} from '@/src/features/bootstrap/types';

export type {
  BootstrapActiveCycle,
  DeadlineWarningItem,
  HomeBlockingNotice,
  HomeMode,
  HomePlanBlock,
  HomeProgress,
  PlanPeriod,
};

// GET /home/current = FINALIZING일 때만 채워진다.
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

// GET /home/current = CHECK_IN_RESULT일 때만 채워진다.
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

// 홈 전용 endpoint 응답 전체 구조. GET /bootstrap의 BootstrapHome과 logicalDate~planBlocks까지는
// 필드가 같지만 finalizing·checkInResult는 GET /home/current에만 있다.
export type HomeCurrentResponse = {
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

export type PlanBlockCheckStateResponse = {
  planBlock: HomePlanBlock;
  progress: HomeProgress;
};

export type DeadlineWarningsAcknowledgeResponse = {
  acknowledgedTaskIds: string[];
  acknowledgedAt: string;
};

export type CheckInAcknowledgeResponse = {
  targetCheckInId: string;
  acknowledgedCheckInIds: string[];
  acknowledgedCount: number;
  resultAcknowledgedAt: string;
};

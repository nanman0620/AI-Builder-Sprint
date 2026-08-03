// docs/api/이음_MVP_최종_API_명세서.pdf 9~10절 "GET /home/current" 및 홈 mutation 4개 계약.
// HomeMode·HomeProgress·HomePlanBlock·DeadlineWarningItem·HomeBlockingNotice·FinalizingInfo·
// CheckInResult(및 그 하위 타입)는 bootstrap.data.home과 GET /home/current 응답이 공통으로 쓰는
// 원본 타입이라 src/features/bootstrap/types.ts에 두고 여기서 재수출만 한다.
// bootstrap/types.ts는 이 파일을 import하지 않는다(순환 참조 금지).
import type {
  BootstrapActiveCycle,
  CheckInPlanBlockSummary,
  CheckInPlanStatus,
  CheckInResult,
  DeadlineWarningItem,
  FinalizingInfo,
  HomeBlockingNotice,
  HomeMode,
  HomePlanBlock,
  HomeProgress,
  PlanPeriod,
} from '@/src/features/bootstrap/types';

export type {
  BootstrapActiveCycle,
  CheckInPlanBlockSummary,
  CheckInPlanStatus,
  CheckInResult,
  DeadlineWarningItem,
  FinalizingInfo,
  HomeBlockingNotice,
  HomeMode,
  HomePlanBlock,
  HomeProgress,
  PlanPeriod,
};

// 홈 전용 endpoint 응답 전체 구조. GET /bootstrap의 BootstrapHome과 필드가 완전히 같다(BE-11부터
// bootstrap.data.home이 동일한 계산 결과를 그대로 재사용하므로 finalizing·checkInResult도 포함).
// serverTime은 이 endpoint 응답 최상위에만 있는 필드다.
export type HomeCurrentResponse = {
  serverTime: string;
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

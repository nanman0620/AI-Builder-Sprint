// 홈 화면의 상태 판정·표시용 순수 함수 모음. RN 의존성이 없어 apps/mobile/src/features/bootstrap/route.ts와
// 같은 방식으로 `node --test`로 검증한다.
import type {
  HomeBlockingNotice,
  HomeMode,
  HomePlanBlock,
  HomeProgress,
  PlanPeriod,
} from '../bootstrap/types';

export type VisibleHomeState =
  | 'FINALIZING'
  | 'CHECK_IN_RESULT'
  | 'DEADLINE_WARNING'
  | 'NO_ACTIVE_CYCLE'
  | 'NO_PLANS'
  | 'IN_PROGRESS';

// docs/ai/IMPLEMENTATION_CONTEXT.md 8절 "홈 우선순위" 6단계를 그대로 코드로 옮긴 것.
// DEADLINE_WARNING은 homeMode가 아니라 blockingNotice 위에 얹히는 blocking notice이므로,
// blockingNotice가 없거나 items가 비어 있으면 이 상태를 표시하지 않고 아래 homeMode로 내려간다.
export function resolveVisibleHomeState(input: {
  homeMode: HomeMode;
  blockingNotice: HomeBlockingNotice | null;
}): VisibleHomeState {
  if (input.homeMode === 'FINALIZING') {
    return 'FINALIZING';
  }
  if (input.homeMode === 'CHECK_IN_RESULT') {
    return 'CHECK_IN_RESULT';
  }
  if (input.blockingNotice?.type === 'DEADLINE_WARNING' && input.blockingNotice.items.length > 0) {
    return 'DEADLINE_WARNING';
  }
  if (input.homeMode === 'NO_ACTIVE_CYCLE') {
    return 'NO_ACTIVE_CYCLE';
  }
  if (input.homeMode === 'NO_PLANS') {
    return 'NO_PLANS';
  }
  return 'IN_PROGRESS';
}

// FINALIZING/CHECK_IN_RESULT/DEADLINE_WARNING(blockingNotice)에서만 하단 탭을 숨긴다(§10).
export function shouldHideTabBar(visibleState: VisibleHomeState): boolean {
  return visibleState === 'FINALIZING' || visibleState === 'CHECK_IN_RESULT' || visibleState === 'DEADLINE_WARNING';
}

export type HomeMascotKey = 'DEFAULT' | 'READING' | 'SAD';

// CHECK_IN_RESULT는 점수 기반 마스코트(resolveScoreBand)를 별도로 쓰므로 이 함수의 대상이 아니다.
// UI_REFERENCE.md 4절 자산 용도표: mascot-reading=계획 없음/새 계획 안내, mascot-sad=오류/마감 경고/실패,
// mascot-default=기본/성공/진행.
export function resolveHomeMascotKey(visibleState: Exclude<VisibleHomeState, 'CHECK_IN_RESULT'>): HomeMascotKey {
  if (visibleState === 'DEADLINE_WARNING') {
    return 'SAD';
  }
  if (visibleState === 'NO_ACTIVE_CYCLE') {
    return 'READING';
  }
  return 'DEFAULT';
}

export type ScoreBand = 'SCORE_00' | 'SCORE_30' | 'SCORE_60' | 'SCORE_100';

// UI_REFERENCE.md "점수별 마스코트 선택 규칙": 0<=score<30, 30<=score<60, 60<=score<100, score=100.
export function resolveScoreBand(score: number): ScoreBand {
  if (score >= 100) {
    return 'SCORE_100';
  }
  if (score >= 60) {
    return 'SCORE_60';
  }
  if (score >= 30) {
    return 'SCORE_30';
  }
  return 'SCORE_00';
}

function resolveScoreFeedback(score: number): string {
  const scoreBand = resolveScoreBand(score);

  if (scoreBand === 'SCORE_100') {
    return '오늘 계획을 모두 이어냈어요!';
  }
  if (scoreBand === 'SCORE_60') {
    return '잘하고 있어요, 이 흐름 그대로!';
  }
  if (scoreBand === 'SCORE_30') {
    return '좋아요, 흐름을 만들고 있어요';
  }
  return '괜찮아요, 다시 이어가면 돼요';
}

export function resolveProgressFeedback(percentage: number): string {
  return resolveScoreFeedback(percentage);
}

export function resolveCheckInFeedback(score: number, cycleEnded: boolean): string {
  if (cycleEnded) {
    return '7일의 계획이 모두 끝났어요';
  }

  return resolveScoreFeedback(score);
}

// IN_PROGRESS에서도 서버의 progress.percentage를 같은 네 개의 정적 자산 구간에 매핑한다.
// percentage는 HomeProgress에서 number로 고정되어 있고, 체크 직후 optimistic/server progress가
// 모두 이 함수로 다시 파생되므로 100%가 기본 마스코트로 남지 않는다.
export function resolveProgressMascotBand(percentage: number): ScoreBand {
  return resolveScoreBand(percentage);
}

// logicalDate("YYYY-MM-DD")를 "7월 29일 수요일" 형태로만 표시한다. 기기 로컬 타임존에 따라 날짜가
// 밀리지 않도록 UTC로 고정해 구성·포맷하며, 오늘 날짜를 다시 계산하지 않고 서버가 준 문자열만 그대로 쓴다.
export function formatLogicalDateBadge(logicalDate: string): string {
  const [year, month, day] = logicalDate.split('-').map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  const formatter = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'UTC',
    month: 'long',
    day: 'numeric',
    weekday: 'long',
  });
  return formatter.format(date);
}

// deadlineAt은 항상 "+09:00" 오프셋을 포함한 ISO 문자열이라(§8 마감 경고 예시) Date 파싱 없이
// 앞 10자(YYYY-MM-DD)·11~16자(HH:mm)를 그대로 잘라 쓴다. logicalDate와 같은 "YYYY-MM-DD" 형식만 비교하므로
// 기기 로컬 타임존 영향을 받지 않는다. 마감일이 오늘·내일이 아니면 "M월 D일"로 표시한다.
export function formatDeadlineLabel(deadlineAt: string, logicalDate: string): string {
  const deadlineDate = deadlineAt.slice(0, 10);
  const time = deadlineAt.slice(11, 16);

  if (deadlineDate === logicalDate) {
    return `오늘 ${time} 마감`;
  }

  const [year, month, day] = logicalDate.split('-').map(Number);
  const tomorrow = new Date(Date.UTC(year, month - 1, day + 1));
  const tomorrowLabel = [
    tomorrow.getUTCFullYear(),
    String(tomorrow.getUTCMonth() + 1).padStart(2, '0'),
    String(tomorrow.getUTCDate()).padStart(2, '0'),
  ].join('-');
  if (deadlineDate === tomorrowLabel) {
    return `내일 ${time} 마감`;
  }

  const [, deadlineMonth, deadlineDay] = deadlineDate.split('-').map(Number);
  return `${deadlineMonth}월 ${deadlineDay}일 ${time} 마감`;
}

const PERIOD_LABELS: Record<PlanPeriod, string> = {
  MORNING: '오전',
  AFTERNOON: '오후',
  EVENING: '저녁',
};

// 서버가 내려준 period 값을 화면 문구용 한글 라벨로만 바꾼다. 논리 날짜·분기를 다시 계산하지 않는다.
export function formatPeriodLabel(period: PlanPeriod): string {
  return PERIOD_LABELS[period];
}

// displayOrder 기준 오름차순 정렬. 원본 배열을 변경하지 않는다.
export function sortPlanBlocksByDisplayOrder(planBlocks: HomePlanBlock[]): HomePlanBlock[] {
  return [...planBlocks].sort((a, b) => a.displayOrder - b.displayOrder);
}

// 체크 optimistic update: 로컬에서 해당 PlanBlock의 status/checkedAt만 뒤집는다.
// displayTitle·allocatedMinutes 등 나머지 필드는 그대로 유지한다(재조합 금지).
export function applyOptimisticCheckState(
  planBlocks: HomePlanBlock[],
  planBlockId: string,
  checked: boolean,
  checkedAtIso: string
): HomePlanBlock[] {
  return planBlocks.map((block) =>
    block.id === planBlockId
      ? { ...block, status: checked ? 'CHECKED' : 'PLANNED', checkedAt: checked ? checkedAtIso : null }
      : block
  );
}

export function replacePlanBlock(
  planBlocks: HomePlanBlock[],
  replacement: HomePlanBlock
): HomePlanBlock[] {
  return planBlocks.map((block) => (block.id === replacement.id ? replacement : block));
}

export class PlanBlockPendingRegistry {
  private readonly tokens = new Map<string, symbol>();

  begin(planBlockId: string): symbol | null {
    if (this.tokens.has(planBlockId)) {
      return null;
    }
    const token = Symbol(planBlockId);
    this.tokens.set(planBlockId, token);
    return token;
  }

  owns(planBlockId: string, token: symbol): boolean {
    return this.tokens.get(planBlockId) === token;
  }

  finish(planBlockId: string, token: symbol): boolean {
    if (!this.owns(planBlockId, token)) {
      return false;
    }
    this.tokens.delete(planBlockId);
    return true;
  }

  clear(): void {
    this.tokens.clear();
  }
}

// docs/ai/IMPLEMENTATION_CONTEXT.md 8절 "진행률": 완료 개수/전체 개수(=PLANNED+CHECKED), 시간 비율이 아니다.
// optimistic 상태와 ID별 서버 응답 병합 뒤 모두 같은 계산을 사용해 병렬 응답 순서와 무관하게 유지한다.
export function computeOptimisticProgress(planBlocks: HomePlanBlock[]): HomeProgress {
  const totalCount = planBlocks.length;
  const checkedCount = planBlocks.filter((block) => block.status === 'CHECKED').length;
  const percentage = totalCount > 0 ? Math.round((checkedCount / totalCount) * 100) : 0;
  return { checkedCount, totalCount, percentage };
}

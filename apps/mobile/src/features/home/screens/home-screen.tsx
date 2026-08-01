import { useRouter } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { ErrorView } from '@/src/components/common/error-view';
import { LoadingView } from '@/src/components/common/loading-view';
import { colors, spacing, typography } from '@/src/constants/tokens';
import { useBootstrap } from '@/src/features/bootstrap/bootstrap-context';

import { CheckInPlanRow } from '../components/check-in-plan-row';
import { DeadlineWarningList } from '../components/deadline-warning-list';
import { FinalizingView } from '../components/finalizing-view';
import { HomeHeader } from '../components/home-header';
import { HomeMascot, ScoreMascot } from '../components/home-mascot';
import { PlanBlockRow } from '../components/plan-block-row';
import { ProgressBar } from '../components/progress-bar';
import { ScoreGauge } from '../components/score-gauge';
import { useHideTabBar } from '../hooks/use-hide-tab-bar';
import { useHome } from '../hooks/use-home';
import { formatPeriodLabel, resolveHomeMascotKey, resolveProgressMascotBand, resolveScoreBand, resolveVisibleHomeState, shouldHideTabBar, sortPlanBlocksByDisplayOrder } from '../logic';
import type { CheckInResult } from '../types';

export function HomeScreen() {
  const router = useRouter();
  const { data: bootstrapData, status: bootstrapStatus } = useBootstrap();
  const {
    data,
    isLoading,
    hasLoadError,
    finalizingRefreshError,
    reload,
    isCheckPending,
    checkError,
    toggleCheckState,
    isDeadlineAckPending,
    deadlineAckError,
    acknowledgeDeadlineWarnings,
    isCheckInAckPending,
    checkInAckError,
    acknowledgeCheckIn,
  } = useHome();

  const visibleState = data ? resolveVisibleHomeState(data) : null;
  useHideTabBar(visibleState ? shouldHideTabBar(visibleState) : false);

  if (!data && isLoading) {
    return <LoadingView />;
  }

  if (!data && hasLoadError) {
    return <ErrorView onRetry={reload} />;
  }

  if (!data || !visibleState) {
    return <LoadingView />;
  }

  // 직접 Route 새로고침에서는 홈 조회가 bootstrap 세션 복원보다 먼저 끝날 수 있다.
  // 이 구간에는 fallback을 확정하지 않고, 최신 profile이 context에 반영될 때까지 로딩 화면을 유지한다.
  if (bootstrapStatus === 'idle' || bootstrapStatus === 'loading') {
    return <LoadingView />;
  }

  const nickname = bootstrapData?.profile.nickname?.trim() || null;

  if (visibleState === 'FINALIZING') {
    return <FinalizingView hasRefreshError={finalizingRefreshError} isRefreshing={isLoading} onRetry={reload} />;
  }

  if (visibleState === 'CHECK_IN_RESULT' && data.checkInResult) {
    return (
      <CheckInResultBody
        nickname={nickname}
        result={data.checkInResult}
        isSubmitting={isCheckInAckPending}
        error={checkInAckError}
        onAcknowledge={() => acknowledgeCheckIn(data.checkInResult!.id)}
      />
    );
  }

  if (visibleState === 'DEADLINE_WARNING' && data.blockingNotice) {
    return (
      <View style={styles.screen}>
        <HomeHeader
          logicalDate={data.logicalDate}
          badgeLabel="마감 임박"
          title="마감이 가까운 일이 있어요"
          description="가능한 만큼 먼저 배치했지만, 마감 전 시간이 조금 부족해요."
        />
        <HomeMascot mascotKey={resolveHomeMascotKey('DEADLINE_WARNING')} style={styles.centerMascot} />
        <DeadlineWarningList
          items={data.blockingNotice.items}
          isSubmitting={isDeadlineAckPending}
          error={deadlineAckError}
          onAcknowledge={() => acknowledgeDeadlineWarnings(data.blockingNotice!.items)}
        />
      </View>
    );
  }

  if (visibleState === 'NO_ACTIVE_CYCLE') {
    return (
      <View style={styles.screen}>
        <HomeHeader
          logicalDate={data.logicalDate}
          nickname={nickname}
          title="오늘의 계획을 함께 세워볼까요?"
        />
        <View style={styles.emptyStateGroup}>
          <View style={styles.centerBody}>
            <HomeMascot
              mascotKey={resolveHomeMascotKey('NO_ACTIVE_CYCLE')}
              size={340}
              style={styles.centerMascot}
            />
            <Text style={styles.bodyHeadline}>아직 오늘 계획이 없어요.</Text>
            <Text style={styles.bodyDescription}>
              이음이에게 앞으로 7일의 할 일을 알려주고,{'\n'}오늘의 일정을 시작해 보세요.
            </Text>
          </View>
          <Pressable style={styles.outlineButton} onPress={() => router.push('/(tabs)/plan-management')}>
            <Text style={styles.outlineButtonText}>계획관리에서 등록하기</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  if (visibleState === 'NO_PLANS') {
    return (
      <View style={styles.screen}>
        <HomeHeader
          logicalDate={data.logicalDate}
          nickname={nickname}
          title="발길 닿는 대로, 오늘을 즐겨봐요!"
        />
        <View style={styles.centerBody}>
          <HomeMascot mascotKey={resolveHomeMascotKey('NO_PLANS')} style={styles.centerMascot} />
          <Text style={styles.bodyHeadline}>지금 시간대에는 예정된 계획이 없어요.</Text>
          <Text style={styles.bodyDescription}>잠시 쉬어가도 괜찮아요.</Text>
        </View>
      </View>
    );
  }

  // IN_PROGRESS: 현재 서버 응답의 planBlocks만 표시하고 displayOrder로 정렬한다(§11).
  const planBlocks = sortPlanBlocksByDisplayOrder(data.planBlocks);
  const periodLabel = formatPeriodLabel(data.period);

  return (
    <View style={styles.screen}>
      <HomeHeader
        logicalDate={data.logicalDate}
        title={
          nickname
            ? `${nickname}님의 ${periodLabel} 할 일\n나만의 속도로 잘 가고 있어요!`
            : `안녕하세요,\n${periodLabel} 할 일도 나만의 속도로 잘 가고 있어요!`
        }
      />
      {data.progress ? <ProgressBar percentage={data.progress.percentage} /> : null}
      {data.progress ? (
        <ScoreMascot scoreBand={resolveProgressMascotBand(data.progress.percentage)} style={styles.centerMascot} />
      ) : (
        <HomeMascot mascotKey={resolveHomeMascotKey('IN_PROGRESS')} style={styles.centerMascot} />
      )}
      <Text style={styles.sectionLabel}>지금 할 일</Text>
      {checkError ? <Text style={styles.error}>{checkError}</Text> : null}
      <ScrollView style={styles.list} contentContainerStyle={styles.listContent}>
        {planBlocks.map((block) => (
          <PlanBlockRow key={block.id} block={block} disabled={isCheckPending} onToggle={toggleCheckState} />
        ))}
      </ScrollView>
    </View>
  );
}

// 화면 흐름 PDF 5-7절의 우선순위 규칙(cycleEnded → score>=60 → score<60)만 확인됐고, score>=60 문구는
// UI-011 캡처로 확인했다. score<60·cycleEnded=true 문구는 캡처가 없어 잠정 문구이며 팀 확인이 필요하다.
function resolveCheckInFeedback(result: CheckInResult): string {
  if (result.cycleEnded) {
    return '7일의 계획이 모두 끝났어요';
  }
  if (result.score >= 60) {
    return `${result.score}점, 충분히 잘 이어왔어요`;
  }
  return `${result.score}점, 놓친 계획은 다시 이어뒀어요`;
}

type CheckInResultBodyProps = {
  nickname: string | null;
  result: CheckInResult;
  isSubmitting: boolean;
  error: string | null;
  onAcknowledge: () => void;
};

function CheckInResultBody({ nickname, result, isSubmitting, error, onAcknowledge }: CheckInResultBodyProps) {
  const scoreBand = resolveScoreBand(result.score);
  const periodLabel = formatPeriodLabel(result.period);

  return (
    <View style={styles.screen}>
      <View style={styles.resultHeaderRow}>
        <View style={styles.resultHeaderText}>
          <Text style={styles.resultEyebrow}>
            {nickname ? `${nickname}님의 ${periodLabel} 결과` : `${periodLabel} 결과`}
          </Text>
          <Text style={styles.bodyHeadline}>{resolveCheckInFeedback(result)}</Text>
        </View>
        <ScoreGauge score={result.score} />
      </View>
      <ScoreMascot scoreBand={scoreBand} style={styles.centerMascot} />
      <View style={styles.resultCountsRow}>
        <Text style={styles.resultCount}>✓ 완료 {result.completedPlanCount}</Text>
        <Text style={styles.resultCount}>○ 미완료 {result.notDonePlanCount}</Text>
      </View>
      <ScrollView style={styles.list} contentContainerStyle={styles.listContent}>
        {result.completedPlans.map((plan) => (
          <CheckInPlanRow key={plan.id} displayTitle={plan.displayTitle} completed />
        ))}
        {result.notDonePlans.map((plan) => (
          <CheckInPlanRow key={plan.id} displayTitle={plan.displayTitle} completed={false} />
        ))}
      </ScrollView>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Pressable disabled={isSubmitting} onPress={onAcknowledge} style={[styles.filledButton, isSubmitting && styles.buttonDisabled]}>
        <Text style={styles.filledButtonText}>{periodLabel} 계획 보기</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.background,
  },
  centerBody: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
  },
  emptyStateGroup: {
    flex: 1,
    transform: [{ translateY: -24 }],
  },
  centerMascot: {
    alignSelf: 'center',
    marginVertical: spacing.lg,
  },
  bodyHeadline: {
    ...typography.title,
    color: colors.text,
    textAlign: 'center',
  },
  bodyDescription: {
    ...typography.body,
    color: colors.textSecondary,
    textAlign: 'center',
    marginTop: spacing.xs,
  },
  sectionLabel: {
    ...typography.body,
    fontWeight: '700',
    color: colors.text,
    paddingHorizontal: spacing.lg,
    marginBottom: spacing.sm,
  },
  list: {
    flex: 1,
    paddingHorizontal: spacing.lg,
  },
  listContent: {
    paddingBottom: spacing.lg,
  },
  outlineButton: {
    borderColor: colors.primary,
    borderWidth: 1.5,
    borderRadius: 12,
    paddingVertical: spacing.md,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.lg,
    alignItems: 'center',
  },
  outlineButtonText: {
    ...typography.body,
    color: colors.primary,
    fontWeight: '700',
  },
  filledButton: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: spacing.md,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.lg,
    alignItems: 'center',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  filledButtonText: {
    ...typography.body,
    color: colors.background,
    fontWeight: '700',
  },
  error: {
    ...typography.caption,
    color: colors.error,
    textAlign: 'center',
    marginBottom: spacing.sm,
  },
  resultHeaderRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
  },
  resultHeaderText: {
    flex: 1,
    marginRight: spacing.md,
  },
  resultEyebrow: {
    ...typography.caption,
    color: colors.textSecondary,
    marginBottom: spacing.xs,
  },
  resultCountsRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    marginBottom: spacing.sm,
  },
  resultCount: {
    ...typography.body,
    color: colors.text,
    marginHorizontal: spacing.md,
  },
});

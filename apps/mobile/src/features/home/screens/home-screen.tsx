import { useRouter } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { CircularGauge } from '@/src/components/CircularGauge';
import { ErrorView } from '@/src/components/common/error-view';
import { LoadingView } from '@/src/components/common/loading-view';
import { colors, fonts, spacing, typography } from '@/src/constants/tokens';
import { useBootstrap } from '@/src/features/bootstrap/bootstrap-context';

import { CheckInPlanList } from '../components/check-in-plan-list';
import { CheckInStatusIcon } from '../components/check-in-plan-row';
import { DeadlineWarningList } from '../components/deadline-warning-list';
import { FinalizingView } from '../components/finalizing-view';
import { HomeDateBadge, HomeHeader } from '../components/home-header';
import { HomeMascot, ScoreMascot } from '../components/home-mascot';
import { PlanBlockRow } from '../components/plan-block-row';
import { ProgressBar } from '../components/progress-bar';
import { useHideTabBar } from '../hooks/use-hide-tab-bar';
import { useHome } from '../hooks/use-home';
import { formatPeriodLabel, resolveCheckInFeedback, resolveHomeMascotKey, resolveProgressFeedback, resolveProgressMascotBand, resolveScoreBand, resolveVisibleHomeState, shouldHideTabBar, sortPlanBlocksByDisplayOrder } from '../logic';
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
    pendingPlanBlockIds,
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
          showShopIcon={false}
          titleStyle={styles.deadlineWarningTitle}
          descriptionStyle={styles.deadlineWarningDescription}
          descriptionNumberOfLines={1}
        />
        <HomeMascot
          mascotKey={resolveHomeMascotKey('DEADLINE_WARNING')}
          size={235}
          showBackdrop={false}
          style={styles.centerMascot}
        />
        <DeadlineWarningList
          items={data.blockingNotice.items}
          logicalDate={data.logicalDate}
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
        <ScrollView
          style={styles.emptyStateScroll}
          contentContainerStyle={styles.emptyStateContent}
          bounces={false}>
          <View style={styles.elevatedEmptyStateBody}>
            <HomeMascot
              mascotKey={resolveHomeMascotKey('NO_ACTIVE_CYCLE')}
              size={290}
              style={styles.centerMascot}
            />
            <Text style={styles.bodyHeadline}>아직 오늘 계획이 없어요.</Text>
            <Text style={styles.bodyDescription}>
              이음이에게 앞으로 7일의 할 일을 알려주고,{'\n'}오늘의 일정을 시작해 보세요.
            </Text>
            <Pressable style={styles.outlineButton} onPress={() => router.push('/(tabs)/plan-management')}>
              <Text style={styles.outlineButtonText}>계획관리에서 등록하기</Text>
            </Pressable>
          </View>
        </ScrollView>
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
        <ScrollView
          style={styles.emptyStateScroll}
          contentContainerStyle={styles.emptyStateContent}
          bounces={false}>
          <View style={styles.elevatedEmptyStateBody}>
            <HomeMascot mascotKey={resolveHomeMascotKey('NO_PLANS')} style={styles.centerMascot} />
            <Text style={styles.bodyHeadline}>지금 시간대에는 예정된 계획이 없어요.</Text>
            <Text style={styles.bodyDescription}>잠시 쉬어가도 괜찮아요.</Text>
            <Pressable style={styles.outlineButton} onPress={() => router.push('/(tabs)/plan-management')}>
              <Text style={styles.outlineButtonText}>계획관리에서 등록하기</Text>
            </Pressable>
          </View>
        </ScrollView>
      </View>
    );
  }

  // IN_PROGRESS: 현재 서버 응답의 planBlocks만 표시하고 displayOrder로 정렬한다(§11).
  const planBlocks = sortPlanBlocksByDisplayOrder(data.planBlocks);
  const periodLabel = formatPeriodLabel(data.period);
  const progressFeedback = data.progress
    ? resolveProgressFeedback({
        percentage: data.progress.percentage,
        logicalDate: data.logicalDate,
        currentPeriod: data.period,
        completedPlanCount: data.progress.checkedCount,
        totalPlanCount: data.progress.totalCount,
      })
    : '지금부터 하나씩 시작해 봐요!';

  return (
    <View style={styles.screen}>
      <HomeHeader
        logicalDate={data.logicalDate}
        title={nickname ? `${nickname}님의 ${periodLabel} 할 일` : '안녕하세요,'}
        feedback={nickname ? progressFeedback : `${periodLabel} 할 일도 ${progressFeedback}`}
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
          <PlanBlockRow
            key={block.id}
            block={block}
            disabled={pendingPlanBlockIds.has(block.id)}
            onToggle={toggleCheckState}
          />
        ))}
      </ScrollView>
    </View>
  );
}

type CheckInResultBodyProps = {
  nickname: string | null;
  result: CheckInResult;
  isSubmitting: boolean;
  error: string | null;
  onAcknowledge: () => void;
};

function CheckInResultBody({
  nickname,
  result,
  isSubmitting,
  error,
  onAcknowledge,
}: CheckInResultBodyProps) {
  const scoreBand = resolveScoreBand(result.score);
  const periodLabel = formatPeriodLabel(result.period);
  // API가 완료/미완료를 별도 배열로만 제공하고 공통 displayOrder는 제공하지 않으므로,
  // 각 배열 내부의 서버 순서를 유지한다. 두 배열 사이의 원본 혼합 순서는 복원할 수 없다.
  const resultPlans = [...result.completedPlans, ...result.notDonePlans];

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.resultContent}
      bounces={false}>
      <View style={styles.resultHeaderRow}>
        <View style={styles.resultHeaderText}>
          <View style={styles.resultDateBadge}>
            <HomeDateBadge logicalDate={result.checkDate} />
          </View>
          <Text style={styles.resultEyebrow}>
            {nickname ? `${nickname}님의 ${periodLabel} 결과` : `${periodLabel} 결과`}
          </Text>
          <Text style={[styles.bodyHeadline, styles.resultHeaderTitleText]}>
            {resolveCheckInFeedback(result.score, result.cycleEnded)}
          </Text>
        </View>
        <CircularGauge value={result.score} size={88} />
      </View>
      <ScoreMascot scoreBand={scoreBand} style={styles.centerMascot} />
      <View style={styles.resultCountsRow}>
        <View style={styles.resultCountGroup}>
          <CheckInStatusIcon completed size={20} />
          <Text style={styles.resultCount}>완료 {result.completedPlanCount}</Text>
        </View>
        <View style={styles.resultCountGroup}>
          <CheckInStatusIcon completed={false} size={20} />
          <Text style={styles.resultCount}>미완료 {result.notDonePlanCount}</Text>
        </View>
      </View>
      <CheckInPlanList plans={resultPlans} />
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Pressable
        disabled={isSubmitting}
        onPress={onAcknowledge}
        style={[styles.filledButton, isSubmitting && styles.buttonDisabled]}>
        <Text style={styles.filledButtonText}>{periodLabel} 계획 보기</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.background,
  },
  deadlineWarningTitle: {
    fontSize: 20,
    fontFamily: fonts.bold,
    color: colors.deadlineCardTitle,
    marginLeft: 0,
  },
  deadlineWarningDescription: {
    fontSize: 12,
    fontFamily: fonts.regular,
    color: colors.deadlineDescriptionText,
  },
  emptyStateScroll: {
    flex: 1,
  },
  emptyStateContent: {
    flexGrow: 1,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.xl * 2,
    paddingBottom: spacing.xl,
  },
  elevatedEmptyStateBody: {
    flexGrow: 1,
    alignItems: 'center',
    paddingTop: 0,
    gap: spacing.sm,
  },
  centerMascot: {
    alignSelf: 'center',
    marginBottom: 0,
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
    fontFamily: fonts.bold,
    color: colors.text,
    paddingHorizontal: spacing.lg,
    marginTop: -30,
    marginBottom: spacing.sm + 10,
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
    minHeight: 52,
    alignSelf: 'stretch',
    marginTop: spacing.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  outlineButtonText: {
    ...typography.body,
    color: colors.primary,
    fontFamily: fonts.bold,
  },
  filledButton: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: spacing.md,
    marginHorizontal: spacing.lg,
    marginTop: spacing.md+10,
    marginBottom: spacing.lg,
    alignItems: 'center',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  filledButtonText: {
    ...typography.body,
    color: colors.background,
    fontFamily: fonts.bold,
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
  resultContent: {
    flexGrow: 1,
    paddingBottom: spacing.lg,
  },
  resultHeaderText: {
    flex: 1,
    marginRight: spacing.md,
  },
  resultDateBadge: {
    alignSelf: 'flex-start',
    marginBottom: spacing.sm,
  },
  resultEyebrow: {
    fontSize: 15,
    lineHeight: 20,
    fontFamily: fonts.medium,
    color: colors.textSecondary,
    marginTop: 2,
    marginBottom: spacing.xs,
    marginLeft: 6,
  },
  resultHeaderTitleText: {
    fontSize: 17,
    lineHeight: typography.title.lineHeight,
    fontFamily: fonts.bold,
    marginLeft: -42,
    marginTop: -2,
  },
  resultCountsRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    gap: 48,
    marginBottom: 12,
    marginTop: -10,
  },
  resultCountGroup: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  resultCount: {
    ...typography.body,
    color: colors.text,
  },
});

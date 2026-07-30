import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, spacing, typography } from '@/src/constants/tokens';

import { HomeMascot } from './home-mascot';

type FinalizingViewProps = {
  hasRefreshError: boolean;
  isRefreshing: boolean;
  onRetry: () => void;
};

// UI-010: 하단 탭 없이 전체 화면으로 표시(§10). 조회 실패는 정산 실패가 아니므로 화면을 유지하고
// 전용 문구 + 다시 확인 버튼만 보여준다(§7).
export function FinalizingView({ hasRefreshError, isRefreshing, onRetry }: FinalizingViewProps) {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>계획을 다시 잇고 있어요</Text>
      <Text style={styles.description}>이전 결과를 반영해 앞으로의 계획을 재조정하고 있어요</Text>
      <HomeMascot mascotKey="DEFAULT" size={160} style={styles.mascot} />
      {hasRefreshError ? (
        <View style={styles.statusArea}>
          <Text style={styles.errorTitle}>진행 상태를 확인하지 못했어요.</Text>
          <Text style={styles.errorDescription}>작업은 계속 진행 중일 수 있어요.</Text>
          <Pressable
            disabled={isRefreshing}
            style={[styles.retryButton, isRefreshing && styles.retryButtonDisabled]}
            onPress={onRetry}>
            <Text style={styles.retryButtonText}>다시 확인</Text>
          </Pressable>
        </View>
      ) : (
        <View style={styles.statusArea}>
          <Text style={styles.statusLabel}>이음이가 정리하는 중</Text>
          <ActivityIndicator size="small" color={colors.primary} style={styles.spinner} />
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.background,
    paddingHorizontal: spacing.lg,
  },
  title: {
    ...typography.title,
    color: colors.text,
    textAlign: 'center',
  },
  description: {
    ...typography.body,
    color: colors.textSecondary,
    textAlign: 'center',
    marginTop: spacing.xs,
  },
  mascot: {
    marginTop: spacing.xl,
    marginBottom: spacing.xl,
  },
  statusArea: {
    alignItems: 'center',
  },
  statusLabel: {
    ...typography.caption,
    color: colors.textSecondary,
  },
  spinner: {
    marginTop: spacing.md,
  },
  errorTitle: {
    ...typography.body,
    color: colors.text,
    textAlign: 'center',
  },
  errorDescription: {
    ...typography.caption,
    color: colors.textSecondary,
    textAlign: 'center',
    marginTop: spacing.xs,
    marginBottom: spacing.md,
  },
  retryButton: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.xl,
  },
  retryButtonDisabled: {
    opacity: 0.6,
  },
  retryButtonText: {
    ...typography.body,
    color: colors.background,
    fontWeight: '700',
  },
});

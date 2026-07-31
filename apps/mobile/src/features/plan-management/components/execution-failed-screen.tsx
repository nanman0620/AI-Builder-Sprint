import { Image, Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, spacing, typography } from '@/src/constants/tokens';

const mascotSad = require('@/assets/brand/mascot-sad.png');

type ExecutionFailedScreenProps = {
  message: string;
  isSubmitting: boolean;
  actionError: string | null;
  onRetry: () => void;
  onCancel: () => void;
};

export function ExecutionFailedScreen({
  message,
  isSubmitting,
  actionError,
  onRetry,
  onCancel,
}: ExecutionFailedScreenProps) {
  return (
    <View style={styles.container}>
      <View style={styles.content}>
        <Image source={mascotSad} style={styles.mascot} resizeMode="contain" />
        <Text style={styles.title}>요청을 반영하지 못했어요</Text>
        <View style={styles.errorSummary}>
          <Text style={styles.errorSummaryText}>{message}</Text>
        </View>
      </View>
      <Text style={styles.description}>다시 시도하면 같은 요청을 재사용해요.</Text>
      {actionError ? <Text style={styles.actionError}>{actionError}</Text> : null}
      <Pressable
        style={[styles.retryButton, isSubmitting && styles.disabled]}
        disabled={isSubmitting}
        onPress={onRetry}>
        <Text style={styles.retryButtonText}>{isSubmitting ? '처리 중...' : '다시 시도'}</Text>
      </Pressable>
      <Pressable
        style={[styles.cancelButton, isSubmitting && styles.disabled]}
        disabled={isSubmitting}
        onPress={onCancel}>
        <Text style={styles.cancelButtonText}>요청 취소</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.lg,
  },
  content: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  mascot: {
    width: 180,
    height: 180,
    marginBottom: spacing.lg,
  },
  title: {
    ...typography.title,
    color: colors.text,
    textAlign: 'center',
  },
  errorSummary: {
    alignSelf: 'stretch',
    borderColor: '#F08080',
    borderWidth: 1,
    borderRadius: 16,
    backgroundColor: '#FDECEC',
    padding: spacing.lg,
    marginTop: spacing.lg,
  },
  errorSummaryText: {
    ...typography.body,
    color: colors.error,
    fontWeight: '700',
  },
  description: {
    ...typography.caption,
    color: colors.textSecondary,
    textAlign: 'center',
    marginBottom: spacing.md,
  },
  actionError: {
    ...typography.caption,
    color: colors.error,
    textAlign: 'center',
    marginBottom: spacing.sm,
  },
  retryButton: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: spacing.md,
    alignItems: 'center',
  },
  retryButtonText: {
    ...typography.body,
    color: colors.background,
    fontWeight: '700',
  },
  cancelButton: {
    paddingVertical: spacing.md,
    alignItems: 'center',
  },
  cancelButtonText: {
    ...typography.body,
    color: colors.primary,
    fontWeight: '700',
  },
  disabled: {
    opacity: 0.5,
  },
});

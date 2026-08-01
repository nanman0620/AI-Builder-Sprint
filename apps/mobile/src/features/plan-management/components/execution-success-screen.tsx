import { Image, Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, fonts, spacing, typography } from '@/src/constants/tokens';

import type { ExecutionCompletedResult } from '../types';

const mascotDefault = require('@/assets/brand/mascot-default.png');

type ExecutionSuccessScreenProps = {
  result: ExecutionCompletedResult | null;
  isSubmitting: boolean;
  error: string | null;
  onAcknowledge: () => void;
};

export function ExecutionSuccessScreen({
  result,
  isSubmitting,
  error,
  onAcknowledge,
}: ExecutionSuccessScreenProps) {
  return (
    <View style={styles.container}>
      <View style={styles.content}>
        <Image source={mascotDefault} style={styles.mascot} resizeMode="contain" />
        <Text style={styles.title}>할 일과 일정을 반영했어요</Text>
        {result ? (
          <View style={styles.summary}>
            <Text style={styles.summaryText}>
              할 일 {result.taskCount}개 · 고정 일정 {result.fixedScheduleCount}개
            </Text>
          </View>
        ) : null}
        <Text style={styles.description}>현재 시간대 계획만 홈에서 바로 확인할 수 있어요.</Text>
      </View>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Pressable
        style={[styles.button, isSubmitting && styles.disabled]}
        disabled={isSubmitting}
        onPress={onAcknowledge}>
        <Text style={styles.buttonText}>
          {isSubmitting ? '확인 중...' : '홈에서 현재 계획 보기'}
        </Text>
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
  summary: {
    alignSelf: 'stretch',
    borderColor: '#5C9F83',
    borderWidth: 1,
    borderRadius: 16,
    backgroundColor: '#E8F7F0',
    padding: spacing.lg,
    marginTop: spacing.lg,
  },
  summaryText: {
    ...typography.body,
    color: '#4F8A72',
    fontFamily: fonts.bold,
  },
  description: {
    ...typography.caption,
    color: colors.textSecondary,
    textAlign: 'center',
    marginTop: spacing.md,
  },
  error: {
    ...typography.caption,
    color: colors.error,
    textAlign: 'center',
    marginBottom: spacing.sm,
  },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: spacing.md,
    alignItems: 'center',
  },
  buttonText: {
    ...typography.body,
    color: colors.background,
    fontFamily: fonts.bold,
  },
  disabled: {
    opacity: 0.5,
  },
});

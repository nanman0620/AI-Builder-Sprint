import { Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, spacing, typography } from '@/src/constants/tokens';

// 문구는 docs/ai/IMPLEMENTATION_CONTEXT.md 11절의 일반 오류 표준 문구를 기본값으로 사용한다.
const DEFAULT_TITLE = '정보를 불러오지 못했어요.';
const DEFAULT_DESCRIPTION = '잠시 후 다시 시도해 주세요.';

type ErrorViewProps = {
  title?: string;
  description?: string;
  retryLabel?: string;
  onRetry?: () => void;
};

export function ErrorView({
  title = DEFAULT_TITLE,
  description = DEFAULT_DESCRIPTION,
  retryLabel = '다시 시도',
  onRetry,
}: ErrorViewProps) {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>{title}</Text>
      <Text style={styles.description}>{description}</Text>
      {onRetry ? (
        <Pressable style={styles.button} onPress={onRetry}>
          <Text style={styles.buttonText}>{retryLabel}</Text>
        </Pressable>
      ) : null}
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
    ...typography.caption,
    color: colors.textSecondary,
    textAlign: 'center',
    marginTop: spacing.xs,
    marginBottom: spacing.lg,
  },
  button: {
    alignSelf: 'stretch',
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.xl,
  },
  buttonText: {
    ...typography.body,
    color: colors.background,
    fontWeight: '700',
    textAlign: 'center',
  },
});

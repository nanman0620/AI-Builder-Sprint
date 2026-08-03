import { ActivityIndicator, Image, Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, fonts, spacing, typography } from '@/src/constants/tokens';

const mascotDefault = require('@/assets/brand/mascot-default.png');

type ExecutingScreenProps = {
  refreshError: string | null;
  isRefreshing: boolean;
  onRefresh: () => void;
};

export function ExecutingScreen({
  refreshError,
  isRefreshing,
  onRefresh,
}: ExecutingScreenProps) {
  return (
    <View style={styles.container}>
      <View style={styles.content}>
        <Text style={styles.title}>내 일정에 맞춰{'\n'}7일 계획을 이어보고 있어요.</Text>
        <Image source={mascotDefault} style={styles.mascot} resizeMode="contain" />
        <Text style={styles.description}>이음이가 계획을 이어볼게요.</Text>
        <ActivityIndicator color={colors.primary} size="large" />
        {refreshError ? (
          <View style={styles.errorArea}>
            <Text style={styles.error}>{refreshError}</Text>
            <Pressable
              style={[styles.refreshButton, isRefreshing && styles.disabled]}
              disabled={isRefreshing}
              onPress={onRefresh}>
              <Text style={styles.refreshButtonText}>
                {isRefreshing ? '확인 중...' : '다시 확인'}
              </Text>
            </Pressable>
          </View>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  content: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
  },
  title: {
    ...typography.title,
    color: colors.text,
    textAlign: 'center',
  },
  mascot: {
    width: 240,
    height: 240,
    marginVertical: spacing.lg-20,
  },
  description: {
    ...typography.body,
    color: colors.textSecondary,
    marginBottom: spacing.md,
  },
  errorArea: {
    alignItems: 'center',
    marginTop: spacing.lg,
  },
  error: {
    ...typography.caption,
    color: colors.error,
    textAlign: 'center',
  },
  refreshButton: {
    borderColor: colors.primary,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    marginTop: spacing.md,
  },
  refreshButtonText: {
    ...typography.body,
    color: colors.primary,
    fontFamily: fonts.bold,
  },
  disabled: {
    opacity: 0.5,
  },
});

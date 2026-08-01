import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { colors, fonts, spacing, typography } from '@/src/constants/tokens';

import type { DeadlineWarningItem } from '../types';

type DeadlineWarningListProps = {
  items: DeadlineWarningItem[];
  isSubmitting: boolean;
  error: string | null;
  onAcknowledge: () => void;
};

// UI-008(복수)·UI-009(단일)이 공유하는 단 하나의 목록 컴포넌트. items.length만 다르다(§8).
// 자동 acknowledge·자동 이동·타이머 기반 이동은 만들지 않는다. 실패 시 이 목록과 화면을 그대로 유지한다.
export function DeadlineWarningList({ items, isSubmitting, error, onAcknowledge }: DeadlineWarningListProps) {
  return (
    <View style={styles.container}>
      <ScrollView style={styles.list} contentContainerStyle={styles.listContent}>
        {items.map((item) => (
          <View key={item.taskId} style={styles.card}>
            <Text style={styles.cardTitle}>{item.title}</Text>
            <Text style={styles.cardDeadline}>{item.deadlineAt}</Text>
            <View style={styles.cardStatsRow}>
              <View style={styles.cardStat}>
                <Text style={styles.cardStatLabel}>필요 시간</Text>
                <Text style={styles.cardStatValue}>{item.requiredMinutes}분</Text>
              </View>
              <View style={styles.cardStat}>
                <Text style={styles.cardStatLabel}>배치 가능</Text>
                <Text style={[styles.cardStatValue, styles.cardStatAvailable]}>{item.availableMinutes}분</Text>
              </View>
              <View style={styles.cardStat}>
                <Text style={styles.cardStatLabel}>부족</Text>
                <Text style={[styles.cardStatValue, styles.cardStatShortage]}>{item.shortageMinutes}분</Text>
              </View>
            </View>
          </View>
        ))}
      </ScrollView>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Pressable
        disabled={isSubmitting}
        onPress={onAcknowledge}
        style={[styles.button, isSubmitting && styles.buttonDisabled]}>
        <Text style={styles.buttonText}>현재 계획 보기</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.lg,
  },
  list: {
    flex: 1,
  },
  listContent: {
    paddingVertical: spacing.md,
  },
  card: {
    backgroundColor: '#FEF3C7',
    borderColor: colors.warning,
    borderWidth: 1,
    borderRadius: 16,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  cardTitle: {
    ...typography.body,
    fontFamily: fonts.bold,
    color: colors.text,
  },
  cardDeadline: {
    ...typography.caption,
    color: colors.warning,
    marginTop: spacing.xs,
    marginBottom: spacing.sm,
  },
  cardStatsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    borderTopWidth: 1,
    borderTopColor: colors.warning,
    paddingTop: spacing.sm,
  },
  cardStat: {
    alignItems: 'center',
  },
  cardStatLabel: {
    ...typography.caption,
    color: colors.textSecondary,
  },
  cardStatValue: {
    ...typography.body,
    fontFamily: fonts.bold,
    color: colors.text,
    marginTop: 2,
  },
  cardStatAvailable: {
    color: '#16A34A',
  },
  cardStatShortage: {
    color: colors.error,
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
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    ...typography.body,
    color: colors.background,
    fontFamily: fonts.bold,
  },
});

import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import Svg, { Path } from 'react-native-svg';

import { colors, fonts, spacing, typography } from '@/src/constants/tokens';

import { formatDeadlineLabel } from '../logic';
import type { DeadlineWarningItem } from '../types';

type DeadlineWarningListProps = {
  items: DeadlineWarningItem[];
  logicalDate: string;
  isSubmitting: boolean;
  error: string | null;
  onAcknowledge: () => void;
};

// UI-008(복수)·UI-009(단일)이 공유하는 단 하나의 목록 컴포넌트. items.length만 다르다(§8).
// 자동 acknowledge·자동 이동·타이머 기반 이동은 만들지 않는다. 실패 시 이 목록과 화면을 그대로 유지한다.
export function DeadlineWarningList({ items, logicalDate, isSubmitting, error, onAcknowledge }: DeadlineWarningListProps) {
  const lastItem = items[items.length - 1];

  return (
    <View style={styles.container}>
      <ScrollView style={styles.list} contentContainerStyle={styles.listContent}>
        {items.map((item) => (
          <View key={item.taskId} style={styles.itemWrapper}>
            <View style={styles.card}>
              <View style={styles.cardHeaderRow}>
                <View style={styles.cardIcon}>
                  <Svg width={20} height={18} viewBox="0 0 20 18" style={styles.cardIconTriangle}>
                    <Path
                      d="M10 1 L18.5 17 L1.5 17 Z"
                      stroke={colors.deadlineCardIcon}
                      strokeWidth={1.6}
                      strokeLinejoin="round"
                      strokeLinecap="round"
                      fill="none"
                    />
                  </Svg>
                  <Text style={styles.cardIconText}>!</Text>
                </View>
                <View style={styles.cardHeaderText}>
                  <Text style={styles.cardTitle}>{item.title}</Text>
                  <Text style={styles.cardDeadline}>{formatDeadlineLabel(item.deadlineAt, logicalDate)}</Text>
                </View>
              </View>
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
          </View>
        ))}
        {lastItem ? (
          <Text style={styles.cardDescription}>
            오후·저녁에 {lastItem.availableMinutes}분을 우선 배치했어요.{'\n'}
            남은 {lastItem.shortageMinutes}분은 할 일에 그대로 남겨뒀어요.
          </Text>
        ) : null}
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
    paddingBottom: spacing.lg,
  },
  list: {
    flex: 1,
  },
  listContent: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  itemWrapper: {
    marginBottom: spacing.sm,
  },
  card: {
    backgroundColor: colors.deadlineCardBackground,
    borderColor: colors.deadlineCardBorder,
    borderWidth: 1,
    borderRadius: 16,
    paddingHorizontal: 20,
    paddingVertical: 16,
  },
  cardHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  cardIcon: {
    width: 24,
    height: 24,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: spacing.sm,
  },
  cardIconTriangle: {
    position: 'absolute',
  },
  cardIconText: {
    fontSize: 11,
    lineHeight: 13,
    fontFamily: fonts.bold,
    color: colors.deadlineCardIcon,
    marginTop: 3,
  },
  cardHeaderText: {
    flex: 1,
  },
  cardTitle: {
    fontSize: 14,
    lineHeight: 20,
    fontFamily: fonts.bold,
    color: colors.deadlineCardTitle,
  },
  cardDeadline: {
    fontSize: 10,
    lineHeight: 14,
    fontFamily: fonts.bold,
    color: colors.deadlineCardDeadline,
    marginTop: 2,
  },
  cardStatsRow: {
    flexDirection: 'row',
    borderTopWidth: 1,
    borderTopColor: colors.deadlineCardBorder,
    paddingTop: spacing.sm,
  },
  cardStat: {
    flex: 1,
    alignItems: 'center',
  },
  cardStatLabel: {
    fontSize: 10,
    lineHeight: 14,
    fontFamily: fonts.semiBold,
    color: colors.deadlineCardStatLabel,
  },
  cardStatValue: {
    fontSize: 14,
    lineHeight: 20,
    fontFamily: fonts.bold,
    color: colors.deadlineCardTitle,
    marginTop: 2,
  },
  cardStatAvailable: {
    color: colors.deadlineCardAvailable,
  },
  cardStatShortage: {
    color: colors.deadlineCardShortage,
  },
  cardDescription: {
    fontSize: 10,
    lineHeight: 18,
    fontFamily: fonts.regular,
    color: colors.deadlineDescriptionText,
    textAlign: 'center',
    marginTop: spacing.sm,
  },
  error: {
    ...typography.caption,
    color: colors.error,
    textAlign: 'center',
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
  },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    marginHorizontal: 30,
    paddingVertical: 14,
    alignItems: 'center',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    fontSize: 16,
    fontFamily: fonts.bold,
    color: colors.background,
  },
});

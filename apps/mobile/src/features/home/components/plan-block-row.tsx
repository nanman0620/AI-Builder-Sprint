import { Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, fonts, planBlockVisuals, spacing, typography } from '@/src/constants/tokens';

import type { HomePlanBlock } from '../types';

type PlanBlockRowProps = {
  block: HomePlanBlock;
  disabled: boolean;
  onToggle: (planBlockId: string) => void;
};

// IN_PROGRESS(UI-007)에서만 쓰는 체크 가능한 PlanBlock 행. 제목은 서버 displayTitle을 그대로 출력하며
// title/allocatedAmountText/allocatedMinutes를 조합하거나 displayTitle을 파싱하지 않는다(§6).
export function PlanBlockRow({ block, disabled, onToggle }: PlanBlockRowProps) {
  const isChecked = block.status === 'CHECKED';

  return (
    <Pressable
      disabled={disabled}
      accessibilityState={{ disabled }}
      onPress={() => onToggle(block.id)}
      style={[styles.row, isChecked && styles.rowChecked]}>
      <View style={[styles.checkbox, isChecked && styles.checkboxChecked]}>
        {isChecked ? <Text style={styles.checkmark}>✓</Text> : null}
      </View>
      <Text style={styles.title} numberOfLines={2}>
        {block.displayTitle}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: planBlockVisuals.borderWidth,
    borderColor: planBlockVisuals.borderColor,
    borderRadius: planBlockVisuals.borderRadius,
    paddingVertical: spacing.sm +6,
    paddingHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  rowChecked: {
    backgroundColor: colors.primarySoft,
    borderColor: planBlockVisuals.checkedBorderColor,
  },
  checkbox: {
    width: planBlockVisuals.checkSize,
    height: planBlockVisuals.checkSize,
    borderRadius: planBlockVisuals.checkSize / 2,
    borderWidth: planBlockVisuals.checkBorderWidth,
    borderColor: planBlockVisuals.borderColor,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: spacing.sm,
  },
  checkboxChecked: {
    backgroundColor: planBlockVisuals.checkedBorderColor,
    borderColor: planBlockVisuals.checkedBorderColor,
  },
  checkmark: {
    color: colors.background,
    fontSize: 13,
    fontFamily: fonts.bold,
  },
  title: {
    ...typography.body,
    color: colors.text,
    flex: 1,
  },
});

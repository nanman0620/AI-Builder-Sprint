import { Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, spacing, typography } from '@/src/constants/tokens';

import type { HomePlanBlock } from '../types';

type PlanBlockRowProps = {
  block: HomePlanBlock;
  disabled: boolean;
  onToggle: (planBlockId: string, nextChecked: boolean) => void;
};

// IN_PROGRESS(UI-007)에서만 쓰는 체크 가능한 PlanBlock 행. 제목은 서버 displayTitle을 그대로 출력하며
// title/allocatedAmountText/allocatedMinutes를 조합하거나 displayTitle을 파싱하지 않는다(§6).
export function PlanBlockRow({ block, disabled, onToggle }: PlanBlockRowProps) {
  const isChecked = block.status === 'CHECKED';

  return (
    <Pressable
      disabled={disabled}
      onPress={() => onToggle(block.id, !isChecked)}
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
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 16,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  rowChecked: {
    backgroundColor: colors.primarySoft,
    borderColor: colors.primarySoft,
  },
  checkbox: {
    width: 24,
    height: 24,
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: spacing.sm,
  },
  checkboxChecked: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  checkmark: {
    color: colors.background,
    fontSize: 13,
    fontWeight: '700',
  },
  title: {
    ...typography.body,
    color: colors.text,
    flex: 1,
  },
});

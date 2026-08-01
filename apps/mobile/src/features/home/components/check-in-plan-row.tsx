import { StyleSheet, Text, View } from 'react-native';

import { colors, fonts, spacing, typography } from '@/src/constants/tokens';

type CheckInPlanRowProps = {
  displayTitle: string;
  completed: boolean;
};

// CHECK_IN_RESULT(UI-011) 전용 읽기 전용 행. 캘린더는 조회 전용이라는 규칙과 같은 맥락으로
// 여기서도 체크 입력을 받지 않고 완료 여부만 시각적으로 보여준다. displayTitle을 그대로 출력한다(§9).
export function CheckInPlanRow({ displayTitle, completed }: CheckInPlanRowProps) {
  return (
    <View style={[styles.row, completed && styles.rowCompleted]}>
      <View style={[styles.marker, completed && styles.markerCompleted]}>
        {completed ? <Text style={styles.checkmark}>✓</Text> : null}
      </View>
      <Text style={styles.title} numberOfLines={2}>
        {displayTitle}
      </Text>
    </View>
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
  rowCompleted: {
    backgroundColor: colors.primarySoft,
    borderColor: colors.primarySoft,
  },
  marker: {
    width: 24,
    height: 24,
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: spacing.sm,
  },
  markerCompleted: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
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

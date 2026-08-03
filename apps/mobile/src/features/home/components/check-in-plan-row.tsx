import { StyleSheet, Text, View } from 'react-native';

import { colors, fonts, typography } from '@/src/constants/tokens';

type CheckInPlanRowProps = {
  displayTitle: string;
  completed: boolean;
};

type CheckInStatusIconProps = {
  completed: boolean;
  size?: number;
};

export function CheckInStatusIcon({ completed, size = 28 }: CheckInStatusIconProps) {
  return (
    <View
      style={[
        styles.marker,
        { width: size, height: size, borderRadius: size / 2 },
        completed && styles.markerCompleted,
      ]}>
      {completed ? <Text style={[styles.checkmark, { fontSize: size * 0.52 }]}>✓</Text> : null}
    </View>
  );
}

// CHECK_IN_RESULT(UI-011) 전용 읽기 전용 행. 캘린더는 조회 전용이라는 규칙과 같은 맥락으로
// 여기서도 체크 입력을 받지 않고 완료 여부만 시각적으로 보여준다. displayTitle을 그대로 출력한다(§9).
export function CheckInPlanRow({ displayTitle, completed }: CheckInPlanRowProps) {
  return (
    <View style={[styles.row, completed && styles.rowCompleted]}>
      <CheckInStatusIcon completed={completed} />
      <Text style={styles.title} numberOfLines={1}>
        {displayTitle}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    height: 52,
    borderWidth: 1,
    borderColor: colors.checkInIncompleteBorder,
    borderRadius: 26,
    paddingHorizontal: 12,
    gap: 12,
    backgroundColor: colors.surface,
  },
  rowCompleted: {
    backgroundColor: colors.checkInCompletedSurface,
    borderColor: colors.checkInCompletedBorder,
  },
  marker: {
    borderWidth: 1,
    borderColor: colors.checkInIncompleteBorder,
    backgroundColor: colors.surface,
    alignItems: 'center',
    justifyContent: 'center',
  },
  markerCompleted: {
    backgroundColor: colors.checkInCompletedAccent,
    borderColor: colors.checkInCompletedAccent,
  },
  checkmark: {
    color: colors.background,
    fontFamily: fonts.bold,
    lineHeight: 18,
  },
  title: {
    ...typography.body,
    color: colors.text,
    flex: 1,
  },
});

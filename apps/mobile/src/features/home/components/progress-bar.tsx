import { StyleSheet, Text, useWindowDimensions, View } from 'react-native';

import { Gauge } from '@/src/components/Gauge';
import { colors, spacing, typography } from '@/src/constants/tokens';

type ProgressBarProps = {
  percentage: number;
};

// UI-007: "70% 달성" + 선형 게이지. percentage는 서버 progress를 그대로 쓰고 여기서 재계산하지 않는다.
export function ProgressBar({ percentage }: ProgressBarProps) {
  const clamped = Math.max(0, Math.min(100, percentage));
  const { width: screenWidth } = useWindowDimensions();
  const gaugeWidth = screenWidth - spacing.lg * 2;

  return (
    <View style={styles.container}>
      <Text style={styles.label}>{clamped}% 달성</Text>
      <Gauge progress={clamped} width={gaugeWidth} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: spacing.lg,
    marginTop: spacing.md,
  },
  label: {
    ...typography.caption,
    color: colors.textSecondary,
    marginBottom: spacing.xs,
  },
});

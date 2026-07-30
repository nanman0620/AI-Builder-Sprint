import { StyleSheet, Text, View } from 'react-native';

import { colors, typography } from '@/src/constants/tokens';

const SIZE = 88;
const BORDER_WIDTH = 8;

type ScoreGaugeProps = {
  score: number;
};

// 원형 점수 게이지. react-native-svg 등 신규 패키지 없이 View+borderRadius만으로 만든 안정적인 형태다.
// score 비율만큼 원을 실제로 채우는 동적 arc는 만들지 않고, 고정된 원형 배지 안에 점수 숫자만 표시한다
// (§9: "복잡한 동적 원형 arc는 필수 기능이 모두 끝난 후에만 검토"). 정밀한 arc가 필요해지면
// react-native-svg 도입 여부를 팀과 별도로 논의해야 한다.
export function ScoreGauge({ score }: ScoreGaugeProps) {
  return (
    <View style={styles.ring}>
      <Text style={styles.scoreText}>{score}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  ring: {
    width: SIZE,
    height: SIZE,
    borderRadius: SIZE / 2,
    borderWidth: BORDER_WIDTH,
    borderColor: colors.primary,
    backgroundColor: colors.primarySoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  scoreText: {
    ...typography.title,
    color: colors.primary,
  },
});

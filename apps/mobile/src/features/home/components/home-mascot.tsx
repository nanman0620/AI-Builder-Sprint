import type { ReactNode } from 'react';
import { Image, StyleSheet, View, type ImageSourcePropType, type StyleProp, type ViewStyle } from 'react-native';
import Svg, { Circle, Defs, RadialGradient, Stop } from 'react-native-svg';

import { colors } from '@/src/constants/tokens';

import type { HomeMascotKey, ScoreBand } from '../logic';

// UI_REFERENCE.md 4절: Expo/Metro 호환을 위해 파일명을 조합한 동적 require를 쓰지 않고
// 정적 require 매핑만 사용한다.
const MASCOT_SOURCES: Record<HomeMascotKey, ImageSourcePropType> = {
  DEFAULT: require('@/assets/brand/mascot-default.png'),
  READING: require('@/assets/brand/mascot-reading.png'),
  SAD: require('@/assets/brand/mascot-sad.png'),
};

const SCORE_MASCOT_SOURCES: Record<ScoreBand, ImageSourcePropType> = {
  SCORE_00: require('@/assets/brand/mascot-score-00.png'),
  SCORE_30: require('@/assets/brand/mascot-score-30.png'),
  SCORE_60: require('@/assets/brand/mascot-score-60.png'),
  SCORE_100: require('@/assets/brand/mascot-score-100.png'),
};

type HomeMascotProps = {
  mascotKey: HomeMascotKey;
  size?: number;
  style?: StyleProp<ViewStyle>;
};

export function HomeMascot({ mascotKey, size = 160, style }: HomeMascotProps) {
  return (
    <MascotStage contentSize={size} style={style}>
      <Image source={MASCOT_SOURCES[mascotKey]} style={{ width: size, height: size }} resizeMode="contain" />
    </MascotStage>
  );
}

type ScoreMascotProps = {
  scoreBand: ScoreBand;
  style?: StyleProp<ViewStyle>;
};

// UI_REFERENCE.md "CHECK_IN_RESULT 마스코트 배치 규칙": 표시 영역 128x128 고정, contain 유지.
export function ScoreMascot({ scoreBand, style }: ScoreMascotProps) {
  return (
    <MascotStage contentSize={210} style={style}>
      <Image source={SCORE_MASCOT_SOURCES[scoreBand]} style={styles.scoreMascot} resizeMode="contain" />
    </MascotStage>
  );
}

function MascotStage({
  children,
  contentSize,
  style,
}: {
  children: ReactNode;
  contentSize: number;
  style?: StyleProp<ViewStyle>;
}) {
  const stageSize = Math.max(290, contentSize);
  return (
    <View style={[styles.stage, { width: stageSize, height: stageSize }, style]}>
      <Svg pointerEvents="none" width={290} height={290} style={styles.backdrop}>
        <Defs>
          <RadialGradient id="mascotGlow" cx="50%" cy="50%" rx="50%" ry="50%">
            <Stop offset="0%" stopColor={colors.primary} stopOpacity={0.42} />
            <Stop offset="52%" stopColor={colors.primary} stopOpacity={0.26} />
            <Stop offset="72%" stopColor={colors.primary} stopOpacity={0.14} />
            <Stop offset="86%" stopColor={colors.primary} stopOpacity={0.06} />
            <Stop offset="95%" stopColor={colors.primary} stopOpacity={0.018} />
            <Stop offset="100%" stopColor={colors.primary} stopOpacity={0} />
          </RadialGradient>
        </Defs>
        <Circle cx={145} cy={145} r={145} fill="url(#mascotGlow)" />
      </Svg>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  stage: {
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'visible',
  },
  backdrop: {
    position: 'absolute',
    width: 290,
    height: 290,
  },
  scoreMascot: {
    width: 210,
    height: 210,
  },
});

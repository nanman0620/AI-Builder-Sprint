import { Image, StyleSheet, type ImageSourcePropType, type ImageStyle, type StyleProp } from 'react-native';

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
  style?: StyleProp<ImageStyle>;
};

export function HomeMascot({ mascotKey, size = 160, style }: HomeMascotProps) {
  return <Image source={MASCOT_SOURCES[mascotKey]} style={[{ width: size, height: size }, style]} resizeMode="contain" />;
}

type ScoreMascotProps = {
  scoreBand: ScoreBand;
  style?: StyleProp<ImageStyle>;
};

// UI_REFERENCE.md "CHECK_IN_RESULT 마스코트 배치 규칙": 표시 영역 128x128 고정, contain 유지.
export function ScoreMascot({ scoreBand, style }: ScoreMascotProps) {
  return <Image source={SCORE_MASCOT_SOURCES[scoreBand]} style={[styles.scoreMascot, style]} resizeMode="contain" />;
}

const styles = StyleSheet.create({
  scoreMascot: {
    width: 210,
    height: 210,
  },
});

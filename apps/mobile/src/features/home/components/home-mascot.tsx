import { useEffect, useRef, type ReactNode } from 'react';
import { Animated, Easing, Image, StyleSheet, useWindowDimensions, View, type ImageSourcePropType, type StyleProp, type ViewStyle } from 'react-native';
import Svg, { Circle, Defs, Ellipse, Path, RadialGradient, Stop } from 'react-native-svg';

import { colors, spacing } from '@/src/constants/tokens';

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

const SCORE_GROUND_SHADOW_OFFSET: Record<ScoreBand, number> = {
  SCORE_00: 0.18,
  SCORE_30: 0.18,
  SCORE_60: 0.285,
  SCORE_100: 0.285,
};

type HomeMascotProps = {
  mascotKey: HomeMascotKey;
  size?: number;
  style?: StyleProp<ViewStyle>;
  showBackdrop?: boolean;
};

export function HomeMascot({ mascotKey, size = 160, style, showBackdrop = true }: HomeMascotProps) {
  const { width: viewportWidth } = useWindowDimensions();
  const availableWidth = viewportWidth > 0 ? viewportWidth - spacing.lg * 2 : size;
  const renderedSize = Math.min(size, availableWidth);
  const groundShadowOffsetRatio = mascotKey === 'READING' ? 0.245 : 0.285;
  return (
    <MascotStage
      contentSize={renderedSize}
      groundShadowOffsetRatio={showBackdrop ? groundShadowOffsetRatio : null}
      showBackdrop={showBackdrop}
      style={style}>
      <Image
        source={MASCOT_SOURCES[mascotKey]}
        style={{ width: renderedSize, height: renderedSize }}
        resizeMode="contain"
      />
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
    <MascotStage
      contentSize={210}
      groundShadowOffsetRatio={SCORE_GROUND_SHADOW_OFFSET[scoreBand]}
      style={style}>
      {scoreBand === 'SCORE_100' ? <CompletionHeartBurst /> : null}
      <Image source={SCORE_MASCOT_SOURCES[scoreBand]} style={styles.scoreMascot} resizeMode="contain" />
    </MascotStage>
  );
}

function CompletionHeartBurst() {
  const progress = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(progress, {
      toValue: 1,
      duration: 900,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    }).start();
  }, [progress]);

  return (
    <Animated.View
      pointerEvents="none"
      style={[
        styles.completionBurst,
        {
          opacity: progress.interpolate({
            inputRange: [0, 0.12, 0.72, 1],
            outputRange: [0, 1, 0.9, 0],
          }),
          transform: [
            {
              scale: progress.interpolate({
                inputRange: [0, 1],
                outputRange: [0.42, 1.18],
              }),
            },
          ],
        },
      ]}>
      <HeartParticle size={48} style={styles.heartTopLeft} opacity={0.42} />
      <HeartParticle size={34} style={styles.heartUpperLeft} opacity={0.3} />
      <HeartParticle size={42} style={styles.heartTopRight} opacity={0.38} />
      <HeartParticle size={28} style={styles.heartUpperRight} opacity={0.28} />
      <HeartParticle size={38} style={styles.heartSideLeft} opacity={0.34} />
      <HeartParticle size={46} style={styles.heartSideRight} opacity={0.4} />
    </Animated.View>
  );
}

function HeartParticle({
  size,
  style,
  opacity,
}: {
  size: number;
  style: StyleProp<ViewStyle>;
  opacity: number;
}) {
  return (
    <View style={[styles.burstHeart, style, { opacity }]}>
      <Svg width={size} height={size} viewBox="0 0 24 24">
        <Path
          d="M12 21s-7.2-4.35-9.5-8.35C.48 9.13 2.1 4.75 6.25 4.1c2.3-.36 4.1.78 5.75 2.72 1.65-1.94 3.45-3.08 5.75-2.72 4.15.65 5.77 5.03 3.75 8.55C19.2 16.65 12 21 12 21Z"
          fill={colors.primary}
        />
      </Svg>
    </View>
  );
}

function MascotStage({
  children,
  contentSize,
  groundShadowOffsetRatio = null,
  showBackdrop = true,
  style,
}: {
  children: ReactNode;
  contentSize: number;
  groundShadowOffsetRatio?: number | null;
  showBackdrop?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const { width: viewportWidth } = useWindowDimensions();
  const availableWidth = viewportWidth > 0 ? viewportWidth - spacing.lg * 2 : 290;
  const stageSize = Math.max(contentSize, Math.min(290, availableWidth));
  return (
    <View style={[styles.stage, { width: stageSize, height: stageSize }, style]}>
      <Svg pointerEvents="none" width={stageSize} height={stageSize} style={styles.backdrop}>
        <Defs>
          <RadialGradient id="mascotGlow" cx="50%" cy="50%" rx="50%" ry="50%">
            <Stop offset="0%" stopColor={colors.primary} stopOpacity={0.42} />
            <Stop offset="52%" stopColor={colors.primary} stopOpacity={0.26} />
            <Stop offset="72%" stopColor={colors.primary} stopOpacity={0.14} />
            <Stop offset="86%" stopColor={colors.primary} stopOpacity={0.06} />
            <Stop offset="95%" stopColor={colors.primary} stopOpacity={0.018} />
            <Stop offset="100%" stopColor={colors.primary} stopOpacity={0} />
          </RadialGradient>
          <RadialGradient id="mascotGroundShadow" cx="50%" cy="50%" rx="50%" ry="50%">
            <Stop offset="0%" stopColor={colors.primary} stopOpacity={0.44} />
            <Stop offset="68%" stopColor={colors.primary} stopOpacity={0.2} />
            <Stop offset="100%" stopColor={colors.primary} stopOpacity={0} />
          </RadialGradient>
        </Defs>
        {showBackdrop ? (
          <Circle cx={stageSize / 2} cy={stageSize / 2} r={stageSize / 2} fill="url(#mascotGlow)" />
        ) : null}
        {groundShadowOffsetRatio !== null ? (
          <Ellipse
            cx={stageSize / 2}
            cy={stageSize / 2 + contentSize * groundShadowOffsetRatio}
            rx={contentSize * 0.34}
            ry={contentSize * 0.04}
            fill="url(#mascotGroundShadow)"
          />
        ) : null}
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
  },
  scoreMascot: {
    width: 210,
    height: 210,
  },
  completionBurst: {
    position: 'absolute',
    width: 278,
    height: 238,
    alignItems: 'center',
    justifyContent: 'center',
  },
  burstHeart: {
    position: 'absolute',
  },
  heartTopLeft: {
    left: 12,
    top: 42,
    transform: [{ rotate: '-16deg' }],
  },
  heartUpperLeft: {
    left: 72,
    top: 8,
    transform: [{ rotate: '10deg' }],
  },
  heartTopRight: {
    right: 12,
    top: 34,
    transform: [{ rotate: '14deg' }],
  },
  heartUpperRight: {
    right: 76,
    top: 4,
    transform: [{ rotate: '-10deg' }],
  },
  heartSideLeft: {
    left: 0,
    top: 128,
    transform: [{ rotate: '-8deg' }],
  },
  heartSideRight: {
    right: -2,
    top: 120,
    transform: [{ rotate: '10deg' }],
  },
});

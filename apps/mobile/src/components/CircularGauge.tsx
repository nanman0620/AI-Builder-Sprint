import { useEffect, useId, useRef, useState } from 'react';
import { Animated, Easing, Platform, StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, Defs, LinearGradient, Stop } from 'react-native-svg';

import { fonts } from '@/src/constants/tokens';

const VIEW_BOX_SIZE = 25.5;
const CENTER = 12.75;
const RADIUS = 11;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
const DEFAULT_SIZE = 28;
const DEFAULT_STROKE_WIDTH = 3.5;

export type CircularGaugeProps = {
  value: number;
  size?: number;
  strokeWidth?: number;
  showLabel?: boolean;
  className?: string;
};

function clampValue(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.min(100, Math.max(0, value));
}

export function CircularGauge({
  value,
  size = DEFAULT_SIZE,
  strokeWidth = DEFAULT_STROKE_WIDTH,
  showLabel = true,
  className,
}: CircularGaugeProps) {
  const clampedValue = clampValue(value);
  const gaugeSize = Number.isFinite(size) && size > 0 ? size : DEFAULT_SIZE;
  const gaugeStrokeWidth =
    Number.isFinite(strokeWidth) && strokeWidth > 0
      ? strokeWidth
      : DEFAULT_STROKE_WIDTH;
  const gradientId = `circular-gauge-${useId().replace(/:/g, '')}`;
  const dashOffset = useRef(new Animated.Value(CIRCUMFERENCE)).current;
  const [renderedDashOffset, setRenderedDashOffset] = useState(CIRCUMFERENCE);

  useEffect(() => {
    const listenerId = dashOffset.addListener(({ value: nextDashOffset }) => {
      setRenderedDashOffset(nextDashOffset);
    });
    return () => dashOffset.removeListener(listenerId);
  }, [dashOffset]);

  useEffect(() => {
    const animation = Animated.timing(dashOffset, {
      toValue: CIRCUMFERENCE * (1 - clampedValue / 100),
      duration: 500,
      easing: Easing.out(Easing.ease),
      useNativeDriver: false,
    });
    animation.start();
    return () => animation.stop();
  }, [clampedValue, dashOffset]);

  // NativeWind가 없는 현재 프로젝트에서는 className을 웹 호환 prop으로만 전달한다.
  const classNameProps = Platform.OS === 'web' && className ? { className } : {};
  const labelSize = gaugeSize * (8 / DEFAULT_SIZE);

  return (
    <View
      {...classNameProps}
      role="progressbar"
      aria-valuenow={clampedValue}
      aria-valuemin={0}
      aria-valuemax={100}
      accessibilityRole="progressbar"
      accessibilityValue={{ min: 0, max: 100, now: clampedValue }}
      style={[styles.container, { width: gaugeSize, height: gaugeSize }]}>
      <Svg width="100%" height="100%" viewBox={`0 0 ${VIEW_BOX_SIZE} ${VIEW_BOX_SIZE}`}>
        <Defs>
          <LinearGradient
            id={gradientId}
            gradientUnits="userSpaceOnUse"
            x1={1.75}
            x2={23.75}
            y1={1.75}
            y2={1.75}>
            <Stop offset="0%" stopColor="#A83DE2" />
            <Stop offset="100%" stopColor="#DF78F6" />
          </LinearGradient>
        </Defs>
        <Circle
          cx={CENTER}
          cy={CENTER}
          r={RADIUS}
          fill="none"
          stroke="#CB72FF"
          strokeOpacity={0.2}
          strokeWidth={gaugeStrokeWidth}
        />
        <Circle
          cx={CENTER}
          cy={CENTER}
          r={RADIUS}
          fill="none"
          stroke={`url(#${gradientId})`}
          strokeWidth={gaugeStrokeWidth}
          strokeLinecap="round"
          strokeDasharray={[CIRCUMFERENCE, CIRCUMFERENCE]}
          strokeDashoffset={renderedDashOffset}
          transform={`rotate(-90 ${CENTER} ${CENTER})`}
        />
      </Svg>
      {showLabel ? (
        <View style={styles.labelContainer}>
          <Text
            numberOfLines={1}
            style={[styles.label, { fontSize: labelSize, lineHeight: labelSize }]}>
            {Math.round(clampedValue)}
          </Text>
        </View>
      ) : null}
    </View>
  );
}

export function GaugeDemo() {
  return (
    <View style={styles.demoRow}>
      {[0, 45, 75, 100].map((demoValue) => (
        <CircularGauge key={demoValue} value={demoValue} />
      ))}
      <CircularGauge value={75} size={64} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: 'relative',
    alignItems: 'center',
    justifyContent: 'center',
  },
  labelContainer: {
    ...StyleSheet.absoluteFillObject,
    pointerEvents: 'none',
    alignItems: 'center',
    justifyContent: 'center',
  },
  label: {
    color: '#A83DE2',
    fontFamily: fonts.bold,
    textAlign: 'center',
    includeFontPadding: false,
  },
  demoRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 12,
  },
});

import { LinearGradient } from 'expo-linear-gradient';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AccessibilityInfo,
  Animated,
  Easing,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { fonts } from '@/src/constants/tokens';

const TRACK_WIDTH = 250;
const TRACK_HEIGHT = 8;
const TRACK_RADIUS = 4;

const TRACK_COLOR = 'rgba(0, 0, 0, 0.1)';
const GRADIENT_START = '#D791FF';
const GRADIENT_END = '#E6BCFF';
const PARTICLE_COLOR = '#E6BCFF';
const HIGHLIGHT_COLOR = '#FFFFFF';
const DEMO_BUTTON_COLOR = '#F1DEFF';
const DEMO_TEXT_COLOR = '#5E267A';

export type GaugeProps = {
  progress: number;
  width?: number;
  showCompletionEffect?: boolean;
};

type CloudParticleConfig = {
  id: string;
  delay: number;
  duration: number;
  offsetX: number;
  offsetY: number;
  size: number;
};

function clampProgress(progress: number): number {
  if (!Number.isFinite(progress)) {
    return 0;
  }
  return Math.min(100, Math.max(0, progress));
}

function usePrefersReducedMotion(): boolean | null {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState<boolean | null>(null);

  useEffect(() => {
    let mounted = true;
    void AccessibilityInfo.isReduceMotionEnabled().then((enabled) => {
      if (mounted) {
        setPrefersReducedMotion(enabled);
      }
    });
    const subscription = AccessibilityInfo.addEventListener(
      'reduceMotionChanged',
      setPrefersReducedMotion
    );

    return () => {
      mounted = false;
      subscription.remove();
    };
  }, []);

  return prefersReducedMotion;
}

function CloudParticle({
  particle,
  trackWidth,
  onComplete,
}: {
  particle: CloudParticleConfig;
  trackWidth: number;
  onComplete: (id: string) => void;
}) {
  const phase = useRef(new Animated.Value(0)).current;
  const [renderedPhase, setRenderedPhase] = useState(0);

  useEffect(() => {
    const listenerId = phase.addListener(({ value }) => setRenderedPhase(value));
    const animation = Animated.sequence([
      Animated.delay(particle.delay),
      Animated.timing(phase, {
        toValue: 1,
        duration: particle.duration,
        easing: Easing.linear,
        useNativeDriver: false,
      }),
    ]);

    animation.start(({ finished }) => {
      if (finished) {
        onComplete(particle.id);
      }
    });

    return () => {
      animation.stop();
      phase.removeListener(listenerId);
    };
  }, [particle, phase, onComplete]);

  const movementPhase = 1 - Math.pow(1 - renderedPhase, 3);
  const stageProgress = Math.min(1, renderedPhase / 0.35);
  const exitProgress = Math.max(0, (renderedPhase - 0.35) / 0.65);
  const renderedScale = renderedPhase <= 0.35
    ? 0.4 + 0.6 * stageProgress
    : 1 - 0.2 * exitProgress;
  const renderedOpacity = renderedPhase <= 0.35 ? stageProgress : 1 - exitProgress;

  return (
    <View
      style={[
        styles.cloud,
        {
          width: particle.size,
          height: particle.size * 0.65,
          left: trackWidth / 2 - particle.size / 2,
          top: -particle.size * 0.25,
          opacity: renderedOpacity,
          transform: [
            { translateX: particle.offsetX * movementPhase },
            { translateY: particle.offsetY * movementPhase },
            { scale: renderedScale },
          ],
        },
      ]}>
      <View style={[styles.cloudCircle, styles.cloudLeft]} />
      <View style={[styles.cloudCircle, styles.cloudCenter]} />
      <View style={[styles.cloudCircle, styles.cloudRight]} />
    </View>
  );
}

export function Gauge({ progress, width = TRACK_WIDTH, showCompletionEffect = false }: GaugeProps) {
  const clampedProgress = clampProgress(progress);
  const gaugeWidth = Number.isFinite(width) && width > 0 ? width : TRACK_WIDTH;
  const prefersReducedMotion = usePrefersReducedMotion();
  const animatedProgress = useRef(new Animated.Value(0)).current;
  const highlightOpacity = useRef(new Animated.Value(0.4)).current;
  const previousProgress = useRef(0);
  const nextParticleId = useRef(0);
  const [particles, setParticles] = useState<CloudParticleConfig[]>([]);
  const [renderedProgress, setRenderedProgress] = useState(0);
  const [renderedHighlightOpacity, setRenderedHighlightOpacity] = useState(0.4);

  useEffect(() => {
    const listenerId = animatedProgress.addListener(({ value }) => setRenderedProgress(value));
    return () => animatedProgress.removeListener(listenerId);
  }, [animatedProgress]);

  useEffect(() => {
    const listenerId = highlightOpacity.addListener(({ value }) => {
      setRenderedHighlightOpacity(value);
    });
    return () => highlightOpacity.removeListener(listenerId);
  }, [highlightOpacity]);

  useEffect(() => {
    animatedProgress.stopAnimation();
    if (prefersReducedMotion === null) {
      return;
    }
    if (prefersReducedMotion) {
      animatedProgress.setValue(clampedProgress);
      return;
    }

    const animation = Animated.spring(animatedProgress, {
      toValue: clampedProgress,
      stiffness: 120,
      damping: 20,
      mass: 1,
      useNativeDriver: false,
    });
    animation.start();
    return () => animation.stop();
  }, [animatedProgress, clampedProgress, prefersReducedMotion]);

  useEffect(() => {
    highlightOpacity.stopAnimation();
    if (prefersReducedMotion !== false || clampedProgress === 0) {
      highlightOpacity.setValue(0);
      return;
    }

    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(highlightOpacity, {
          toValue: 1,
          duration: 600,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: false,
        }),
        Animated.timing(highlightOpacity, {
          toValue: 0.4,
          duration: 600,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: false,
        }),
      ])
    );
    animation.start();
    return () => animation.stop();
  }, [clampedProgress, highlightOpacity, prefersReducedMotion]);

  useEffect(() => {
    if (prefersReducedMotion === null) {
      return;
    }

    const previous = previousProgress.current;
    previousProgress.current = clampedProgress;

    if (!showCompletionEffect) {
      setParticles([]);
      return;
    }

    if (prefersReducedMotion) {
      setParticles([]);
      return;
    }
    if (previous >= 100 || clampedProgress < 100) {
      return;
    }

    const particleCount = 8 + Math.floor(Math.random() * 5);
    const newParticles = Array.from({ length: particleCount }, () => ({
      id: `gauge-cloud-${++nextParticleId.current}`,
      delay: Math.round(Math.random() * 250),
      duration: Math.round(1200 + Math.random() * 600),
      offsetX: -60 + Math.random() * 120,
      offsetY: -(40 + Math.random() * 40),
      size: 14 + Math.random() * 10,
    }));
    setParticles((current) => [...current, ...newParticles]);
  }, [clampedProgress, prefersReducedMotion, showCompletionEffect]);

  const fillWidth = gaugeWidth * (renderedProgress / 100);
  const highlightX = gaugeWidth * (renderedProgress / 100);

  const removeParticle = useCallback((id: string) => {
    setParticles((current) => current.filter((particle) => particle.id !== id));
  }, []);

  return (
    <View
      accessibilityRole="progressbar"
      accessibilityValue={{ min: 0, max: 100, now: clampedProgress }}
      style={[styles.gauge, { width: gaugeWidth }]}>
      <View style={[styles.track, { width: gaugeWidth }]}>
        <View style={[styles.fillMask, { width: fillWidth }]}>
          <LinearGradient
            colors={[GRADIENT_START, GRADIENT_END]}
            start={{ x: 0, y: 0.5 }}
            end={{ x: 1, y: 0.5 }}
            style={[styles.fixedGradient, { width: gaugeWidth }]}
          />
        </View>
        {prefersReducedMotion === false && clampedProgress > 0 ? (
          <View
            style={[
              styles.highlight,
              {
                opacity: renderedHighlightOpacity,
                transform: [{ translateX: highlightX }],
              },
            ]}
          />
        ) : null}
      </View>
      {showCompletionEffect && prefersReducedMotion === false && particles.length > 0 ? (
        <View style={styles.particleLayer}>
          {particles.map((particle) => (
            <CloudParticle
              key={particle.id}
              particle={particle}
              trackWidth={gaugeWidth}
              onComplete={removeParticle}
            />
          ))}
        </View>
      ) : null}
    </View>
  );
}

export function GaugeDemo() {
  const [progress, setProgress] = useState(0);

  return (
    <View style={styles.demo}>
      <Gauge progress={progress} showCompletionEffect />
      <View style={styles.demoButtons}>
        {[0, 30, 70, 100].map((value) => (
          <Pressable
            key={value}
            accessibilityRole="button"
            onPress={() => setProgress(value)}
            style={styles.demoButton}>
            <Text style={styles.demoButtonText}>{value}%</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  gauge: {
    position: 'relative',
    height: TRACK_HEIGHT,
    overflow: 'visible',
  },
  track: {
    position: 'relative',
    height: TRACK_HEIGHT,
    borderRadius: TRACK_RADIUS,
    backgroundColor: TRACK_COLOR,
    overflow: 'visible',
  },
  fillMask: {
    position: 'absolute',
    left: 0,
    top: 0,
    height: TRACK_HEIGHT,
    borderTopLeftRadius: TRACK_RADIUS,
    borderBottomLeftRadius: TRACK_RADIUS,
    overflow: 'hidden',
  },
  fixedGradient: {
    height: TRACK_HEIGHT,
  },
  highlight: {
    pointerEvents: 'none',
    position: 'absolute',
    left: -3,
    top: 1,
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: HIGHLIGHT_COLOR,
    shadowColor: HIGHLIGHT_COLOR,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.95,
    shadowRadius: 5,
    elevation: 4,
    zIndex: 2,
  },
  particleLayer: {
    ...StyleSheet.absoluteFillObject,
    pointerEvents: 'none',
    overflow: 'visible',
    zIndex: 3,
  },
  cloud: {
    position: 'absolute',
  },
  cloudCircle: {
    position: 'absolute',
    backgroundColor: PARTICLE_COLOR,
    opacity: 0.75,
  },
  cloudLeft: {
    left: '2%',
    bottom: 0,
    width: '55%',
    aspectRatio: 1,
    borderRadius: 999,
  },
  cloudCenter: {
    left: '22%',
    bottom: '8%',
    width: '68%',
    aspectRatio: 1,
    borderRadius: 999,
  },
  cloudRight: {
    right: 0,
    bottom: 0,
    width: '50%',
    aspectRatio: 1,
    borderRadius: 999,
  },
  demo: {
    gap: 24,
    padding: 24,
    alignItems: 'center',
  },
  demoButtons: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'center',
    gap: 8,
  },
  demoButton: {
    minWidth: 52,
    minHeight: 36,
    paddingHorizontal: 12,
    borderRadius: 18,
    backgroundColor: DEMO_BUTTON_COLOR,
    alignItems: 'center',
    justifyContent: 'center',
  },
  demoButtonText: {
    color: DEMO_TEXT_COLOR,
    fontFamily: fonts.bold,
  },
});

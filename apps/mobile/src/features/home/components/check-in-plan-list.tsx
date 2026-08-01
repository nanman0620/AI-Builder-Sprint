import { useState } from 'react';
import { ScrollView, StyleSheet, View, type LayoutChangeEvent, type NativeScrollEvent, type NativeSyntheticEvent } from 'react-native';

import { colors } from '@/src/constants/tokens';

import type { CheckInPlanBlockSummary } from '../types';
import { CheckInPlanRow } from './check-in-plan-row';

type CheckInPlanListProps = {
  plans: CheckInPlanBlockSummary[];
};

const CARD_HEIGHT = 350;
const CARD_PADDING = 16;
const MIN_THUMB_HEIGHT = 32;
const ROW_HEIGHT = 52;
const ROW_GAP = 14;
const CONTENT_BOTTOM_PADDING = 14;

export function CheckInPlanList({ plans }: CheckInPlanListProps) {
  const [viewportHeight, setViewportHeight] = useState(0);
  const [scrollOffset, setScrollOffset] = useState(0);

  const trackHeight = Math.max(0, CARD_HEIGHT - CARD_PADDING * 2);
  const contentHeight = plans.length > 0
    ? plans.length * ROW_HEIGHT + (plans.length - 1) * ROW_GAP + CONTENT_BOTTOM_PADDING
    : 0;
  const maxScrollOffset = Math.max(0, contentHeight - viewportHeight);
  const thumbHeight = contentHeight > 0
    ? Math.min(trackHeight, Math.max(MIN_THUMB_HEIGHT, trackHeight * (viewportHeight / contentHeight)))
    : trackHeight;
  const maxThumbOffset = Math.max(0, trackHeight - thumbHeight);
  const thumbOffset = maxScrollOffset > 0
    ? maxThumbOffset * (Math.min(scrollOffset, maxScrollOffset) / maxScrollOffset)
    : 0;

  const handleLayout = (event: LayoutChangeEvent) => {
    setViewportHeight(event.nativeEvent.layout.height);
  };

  const handleScroll = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
    setScrollOffset(Math.max(0, event.nativeEvent.contentOffset.y));
  };

  return (
    <View style={styles.card}>
      <ScrollView
        onLayout={handleLayout}
        onScroll={handleScroll}
        scrollEventThrottle={16}
        showsVerticalScrollIndicator={false}
        style={styles.scrollView}>
        <View style={styles.content}>
          {plans.map((plan) => (
            <CheckInPlanRow
              key={plan.id}
              displayTitle={plan.displayTitle}
              completed={plan.status === 'COMPLETED'}
            />
          ))}
        </View>
      </ScrollView>
      <View style={styles.scrollbarTrack}>
        <View
          style={[
            styles.scrollbarThumb,
            { height: thumbHeight, transform: [{ translateY: thumbOffset }] },
          ]}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    height: CARD_HEIGHT,
    marginHorizontal: 16,
    padding: CARD_PADDING,
    borderWidth: 1,
    borderColor: colors.checkInListBorder,
    borderRadius: 24,
    backgroundColor: colors.surface,
    position: 'relative',
    overflow: 'hidden',
  },
  scrollView: {
    flex: 1,
  },
  content: {
    gap: 14,
    paddingRight: 8,
    paddingBottom: 14,
  },
  scrollbarTrack: {
    pointerEvents: 'none',
    position: 'absolute',
    top: CARD_PADDING,
    right: 8,
    bottom: CARD_PADDING,
    width: 4,
    borderRadius: 2,
    backgroundColor: colors.checkInScrollbarTrack,
    overflow: 'hidden',
  },
  scrollbarThumb: {
    width: 4,
    borderRadius: 2,
    backgroundColor: colors.checkInScrollbarThumb,
  },
});

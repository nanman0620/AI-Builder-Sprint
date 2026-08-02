import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import {
  Keyboard,
  Platform,
  StyleSheet,
  useWindowDimensions,
  View,
  type KeyboardEvent,
} from 'react-native';

import { colors } from '@/src/constants/tokens';
import { PLAN_COMPOSER_RESTING_BOTTOM_MARGIN } from '@/src/constants/tab-bar';

const COMPOSER_KEYBOARD_GAP = 8;
const PlanKeyboardVisibleContext = createContext(false);

export function usePlanKeyboardVisible(): boolean {
  return useContext(PlanKeyboardVisibleContext);
}

export function PlanKeyboardLayout({ children }: { children: ReactNode }) {
  const { height: windowHeight } = useWindowDimensions();
  const [keyboardInset, setKeyboardInset] = useState(0);
  const [isAndroidKeyboardVisible, setIsAndroidKeyboardVisible] = useState(false);
  const keyboardPadding = Math.max(
    0,
    keyboardInset + COMPOSER_KEYBOARD_GAP - PLAN_COMPOSER_RESTING_BOTTOM_MARGIN,
  );

  useEffect(() => {
    if (Platform.OS !== 'ios') {
      return;
    }

    const handleKeyboardFrame = (event: KeyboardEvent) => {
      Keyboard.scheduleLayoutAnimation(event);
      const overlap = Math.max(0, windowHeight - event.endCoordinates.screenY);
      setKeyboardInset(overlap);
    };
    const handleKeyboardHide = (event: KeyboardEvent) => {
      Keyboard.scheduleLayoutAnimation(event);
      setKeyboardInset(0);
    };

    const frameSubscription = Keyboard.addListener('keyboardWillChangeFrame', handleKeyboardFrame);
    const hideSubscription = Keyboard.addListener('keyboardWillHide', handleKeyboardHide);

    return () => {
      frameSubscription.remove();
      hideSubscription.remove();
    };
  }, [windowHeight]);

  useEffect(() => {
    if (Platform.OS !== 'android') {
      return;
    }

    const showSubscription = Keyboard.addListener('keyboardDidShow', () => {
      setIsAndroidKeyboardVisible(true);
    });
    const hideSubscription = Keyboard.addListener('keyboardDidHide', () => {
      setIsAndroidKeyboardVisible(false);
    });

    return () => {
      showSubscription.remove();
      hideSubscription.remove();
    };
  }, []);

  return (
    <PlanKeyboardVisibleContext.Provider value={isAndroidKeyboardVisible}>
      <View
        style={[
          styles.layout,
          keyboardInset > 0 ? { paddingBottom: keyboardPadding } : null,
        ]}>
        {children}
      </View>
    </PlanKeyboardVisibleContext.Provider>
  );
}

const styles = StyleSheet.create({
  layout: {
    flex: 1,
    backgroundColor: colors.background,
  },
});

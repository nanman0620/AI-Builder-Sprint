import { useEffect, useState, type ReactNode } from 'react';
import {
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  useWindowDimensions,
  View,
  type KeyboardEvent,
} from 'react-native';

import { colors } from '@/src/constants/tokens';
import { PLAN_COMPOSER_RESTING_BOTTOM_MARGIN } from '@/src/constants/tab-bar';

const COMPOSER_KEYBOARD_GAP = 8;

export function PlanKeyboardLayout({ children }: { children: ReactNode }) {
  const { height: windowHeight } = useWindowDimensions();
  const [keyboardInset, setKeyboardInset] = useState(0);
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

  if (Platform.OS === 'android') {
    return (
      <KeyboardAvoidingView behavior="height" style={styles.layout}>
        {children}
      </KeyboardAvoidingView>
    );
  }

  return (
    <View
      style={[
        styles.layout,
        keyboardInset > 0 ? { paddingBottom: keyboardPadding } : null,
      ]}>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  layout: {
    flex: 1,
    backgroundColor: colors.background,
  },
});

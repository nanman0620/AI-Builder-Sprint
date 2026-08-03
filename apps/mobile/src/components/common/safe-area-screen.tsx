import type { PropsWithChildren } from 'react';
import { Platform, StyleSheet, type StyleProp, type ViewStyle } from 'react-native';
import { SafeAreaView, type Edge } from 'react-native-safe-area-context';

import { colors } from '@/src/constants/tokens';

type SafeAreaScreenProps = PropsWithChildren<{
  edges: Edge[];
  style?: StyleProp<ViewStyle>;
}>;

export function SafeAreaScreen({ children, edges, style }: SafeAreaScreenProps) {
  return (
    <SafeAreaView
      edges={Platform.OS === 'web' ? [] : edges}
      style={[styles.screen, style]}>
      {children}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.background,
  },
});

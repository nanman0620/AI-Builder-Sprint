import { ActivityIndicator, Image, StyleSheet, View } from 'react-native';

import { colors, spacing } from '@/src/constants/tokens';

// 앱 최초 실행 동안 흰 화면 대신 표시하는 로고·초기 로딩 화면이다. 하단 탭은 표시하지 않는다.
export function BootstrapSplash() {
  return (
    <View style={styles.container}>
      <Image source={require('@/assets/brand/eum-logo.png')} style={styles.logo} resizeMode="contain" />
      <ActivityIndicator size="small" color={colors.primary} style={styles.spinner} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.background,
  },
  logo: {
    width: 120,
    height: 120,
    marginBottom: spacing.lg,
  },
  spinner: {
    marginTop: spacing.sm,
  },
});

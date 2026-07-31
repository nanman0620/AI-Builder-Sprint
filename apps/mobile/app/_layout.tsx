import { DarkTheme, DefaultTheme, ThemeProvider } from '@react-navigation/native';
import { Stack, useRouter } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useMemo, useRef } from 'react';
import { AppState, type AppStateStatus } from 'react-native';
import 'react-native-reanimated';

import { useColorScheme } from '@/hooks/use-color-scheme';
import { colors } from '@/src/constants/tokens';
import { AppSyncProvider, useAppSync } from '@/src/features/app-sync/app-sync-context';
import { BootstrapProvider, useBootstrap } from '@/src/features/bootstrap/bootstrap-context';
import { resolveAppRoute } from '@/src/features/bootstrap/route';

// 앱이 background/inactive에서 active로 실제 전환될 때만 bootstrap을 재호출한다.
// 최초 mount는 이 변화에 해당하지 않으므로 중복 호출되지 않는다.
function useForegroundBootstrapSync() {
  const router = useRouter();
  const { reset: resetBootstrap, sync } = useBootstrap();
  const {
    handleForegroundBootstrapSuccess,
    reset: resetAppSync,
    setAppActive,
  } = useAppSync();
  const appStateRef = useRef(AppState.currentState);

  useEffect(() => {
    setAppActive(AppState.currentState === 'active');
    const subscription = AppState.addEventListener('change', (next: AppStateStatus) => {
      const previous = appStateRef.current;
      appStateRef.current = next;
      setAppActive(next === 'active');

      const cameToForeground = (previous === 'background' || previous === 'inactive') && next === 'active';
      if (!cameToForeground) {
        return;
      }

      sync().then((result) => {
        const decision = resolveAppRoute(result);

        // session 없음·AUTH_REQUIRED·온보딩 미완료·NICKNAME_CREATION만 강제 이동한다.
        // 계획관리·홈 상태 변경, 네트워크 실패, 알 수 없는 화면은 현재 탭을 그대로 유지한다.
        if (decision.type === 'route' && (decision.href === '/(auth)/login' || decision.href === '/(auth)/onboarding')) {
          if (decision.href === '/(auth)/login') {
            resetAppSync();
            resetBootstrap();
          }
          router.replace(decision.href);
          return;
        }

        if (result.type === 'success') {
          handleForegroundBootstrapSuccess(result.data);
        }
      });
    });

    return () => subscription.remove();
  }, [
    handleForegroundBootstrapSuccess,
    resetAppSync,
    resetBootstrap,
    router,
    setAppActive,
    sync,
  ]);
}

function RootNavigator() {
  useForegroundBootstrapSync();
  const colorScheme = useColorScheme();
  const navigationTheme = useMemo(() => {
    const baseTheme = colorScheme === 'dark' ? DarkTheme : DefaultTheme;

    return {
      ...baseTheme,
      colors: {
        ...baseTheme.colors,
        background: colors.background,
      },
    };
  }, [colorScheme]);

  return (
    <ThemeProvider value={navigationTheme}>
      <Stack screenOptions={{ headerShown: false }}>
        <Stack.Screen name="index" />
        <Stack.Screen name="(auth)" />
        <Stack.Screen name="(tabs)" />
      </Stack>
      <StatusBar style="auto" />
    </ThemeProvider>
  );
}

export default function RootLayout() {
  return (
    <BootstrapProvider>
      <AppSyncProvider>
        <RootNavigator />
      </AppSyncProvider>
    </BootstrapProvider>
  );
}

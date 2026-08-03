import { Stack } from 'expo-router';

import { SafeAreaScreen } from '@/src/components/common/safe-area-screen';

export const unstable_settings = {
  anchor: 'login',
};

export default function AuthLayout() {
  return (
    <SafeAreaScreen edges={['top', 'bottom']}>
      <Stack screenOptions={{ headerShown: false }}>
        <Stack.Screen name="login" />
        <Stack.Screen name="sign-up" />
        <Stack.Screen name="onboarding" />
      </Stack>
    </SafeAreaScreen>
  );
}

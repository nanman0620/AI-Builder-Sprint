import { Tabs } from 'expo-router';
import React from 'react';

import { HapticTab } from '@/components/haptic-tab';
import { IconSymbol } from '@/components/ui/icon-symbol';
import { colors } from '@/src/constants/tokens';
import {
  type ExitDestination,
  PlanExitGuardProvider,
  usePlanExitGuard,
} from '@/src/features/plan-management/contexts/plan-exit-guard-context';

function isExitDestination(routeName: string): routeName is Exclude<ExitDestination, 'back'> {
  return routeName === 'calendar' || routeName === 'home' || routeName === 'settings';
}

function GuardedTabs() {
  const { isGuardActive, requestExit } = usePlanExitGuard();

  return (
    <Tabs
      screenListeners={({ navigation, route }) => ({
        tabPress: (event) => {
          if (!isGuardActive || !isExitDestination(route.name)) {
            return;
          }

          event.preventDefault();
          requestExit(route.name, () => navigation.navigate(route.name));
        },
      })}
      screenOptions={{
        tabBarActiveTintColor: colors.primary,
        tabBarInactiveTintColor: colors.textSecondary,
        headerShown: false,
        tabBarButton: HapticTab,
      }}>
      <Tabs.Screen
        name="calendar"
        options={{
          title: '캘린더',
          tabBarIcon: ({ color }) => <IconSymbol size={28} name="calendar" color={color} />,
        }}
      />
      <Tabs.Screen
        name="home"
        options={{
          title: '홈',
          tabBarIcon: ({ color }) => <IconSymbol size={28} name="house.fill" color={color} />,
        }}
      />
      <Tabs.Screen
        name="plan-management"
        options={{
          title: '계획관리',
          tabBarIcon: ({ color }) => <IconSymbol size={28} name="doc.text.fill" color={color} />,
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: '설정',
          tabBarIcon: ({ color }) => <IconSymbol size={28} name="gearshape.fill" color={color} />,
        }}
      />
    </Tabs>
  );
}

export default function TabLayout() {
  return (
    <PlanExitGuardProvider>
      <GuardedTabs />
    </PlanExitGuardProvider>
  );
}

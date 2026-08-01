import { Tabs } from 'expo-router';
import React from 'react';
import {
  Image,
  StyleSheet,
  View,
  type ImageSourcePropType,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { HapticTab } from '@/components/haptic-tab';
import {
  getTabBarStyle,
  TAB_BAR_ASSET_HEIGHT,
  TAB_BAR_DIVIDER_HEIGHT,
  TAB_BAR_DIVIDER_TOP,
} from '@/src/constants/tab-bar';
import { colors } from '@/src/constants/tokens';
import {
  PlanExitGuardProvider,
  usePlanExitGuard,
  type ExitDestination,
} from '@/src/features/plan-management/contexts/plan-exit-guard-context';

type TabBarVisualProps = {
  defaultSource: ImageSourcePropType;
  focused: boolean;
  selectedSource: ImageSourcePropType;
};

function TabBarVisual({
  defaultSource,
  focused,
  selectedSource,
}: TabBarVisualProps) {
  return (
    <View style={styles.tabVisual}>
      <Image
        accessible={false}
        resizeMode="contain"
        source={focused ? selectedSource : defaultSource}
        style={styles.tabAsset}
      />
    </View>
  );
}

function TabBarBackground() {
  return (
    <View style={styles.tabBarBackground}>
      <View style={styles.tabBarDivider} />
    </View>
  );
}

function isExitDestination(routeName: string): routeName is Exclude<ExitDestination, 'back'> {
  return routeName === 'calendar' || routeName === 'home' || routeName === 'settings';
}

function GuardedTabs() {
  const { isGuardActive, requestExit } = usePlanExitGuard();
  const { bottom: bottomInset } = useSafeAreaInsets();

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
        tabBarBackground: TabBarBackground,
        tabBarButton: HapticTab,
        tabBarLabel: () => null,
        tabBarShowLabel: false,
        tabBarStyle: getTabBarStyle(bottomInset),
      }}>
      <Tabs.Screen
        name="calendar"
        options={{
          title: '캘린더',
          tabBarIcon: ({ focused }) => (
            <TabBarVisual
              defaultSource={require('@/assets/images/REF-018-tab-calendar-default.png')}
              focused={focused}
              selectedSource={require('@/assets/images/REF-019-tab-calendar-selected.png')}
            />
          ),
        }}
      />
      <Tabs.Screen
        name="home"
        options={{
          title: '홈',
          tabBarIcon: ({ focused }) => (
            <TabBarVisual
              defaultSource={require('@/assets/images/REF-023-tab-home-default.png')}
              focused={focused}
              selectedSource={require('@/assets/images/REF-024-tab-home-selected.png')}
            />
          ),
        }}
      />
      <Tabs.Screen
        name="plan-management"
        options={{
          title: '계획관리',
          tabBarIcon: ({ focused }) => (
            <TabBarVisual
              defaultSource={require('@/assets/images/REF-006-tab-plan-default.png')}
              focused={focused}
              selectedSource={require('@/assets/images/REF-005-tab-plan-selected.png')}
            />
          ),
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: '설정',
          tabBarIcon: ({ focused }) => (
            <TabBarVisual
              defaultSource={require('@/assets/images/REF-012-tab-settings-default.png')}
              focused={focused}
              selectedSource={require('@/assets/images/REF-011-tab-settings-selected.png')}
            />
          ),
        }}
      />
    </Tabs>
  );
}

const styles = StyleSheet.create({
  tabVisual: {
    width: 76,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
  },
  tabAsset: {
    width: 72,
    height: TAB_BAR_ASSET_HEIGHT,
  },
  tabBarBackground: {
    pointerEvents: 'none',
    ...StyleSheet.absoluteFillObject,
    top: TAB_BAR_DIVIDER_TOP,
    backgroundColor: colors.background,
    overflow: 'visible',
  },
  tabBarDivider: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    height: TAB_BAR_DIVIDER_HEIGHT,
    backgroundColor: 'rgba(61, 60, 60, 0.5)',
  },
});

export default function TabLayout() {
  return (
    <PlanExitGuardProvider>
      <GuardedTabs />
    </PlanExitGuardProvider>
  );
}

import { useFocusEffect, useNavigation } from '@react-navigation/native';
import { useCallback, useMemo } from 'react';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { getTabBarStyle } from '@/src/constants/tab-bar';

// app/(tabs)/home.tsx는 Tabs의 직접 자식 Screen이라 getParent() 없이 이 화면 자신의
// navigation.setOptions로 tabBarStyle을 바꿀 수 있다(§10).
//
// FINALIZING·CHECK_IN_RESULT·DEADLINE_WARNING(blockingNotice)에서만 하단 탭을 숨긴다.
// homeMode가 바뀌거나 blockingNotice가 해제되면 shouldHide 값이 바뀌어 이 effect가 다시 실행되고,
// 화면이 blur되거나 unmount되면 cleanup에서 항상 원래(표시) 상태로 복원한다.
export function useHideTabBar(shouldHide: boolean) {
  const navigation = useNavigation();
  const { bottom: bottomInset } = useSafeAreaInsets();
  const visibleTabBarStyle = useMemo(() => getTabBarStyle(bottomInset), [bottomInset]);
  const hiddenTabBarStyle = useMemo(() => getTabBarStyle(bottomInset, true), [bottomInset]);

  useFocusEffect(
    useCallback(() => {
      navigation.setOptions({ tabBarStyle: shouldHide ? hiddenTabBarStyle : visibleTabBarStyle });
      return () => {
        navigation.setOptions({ tabBarStyle: visibleTabBarStyle });
      };
    }, [hiddenTabBarStyle, navigation, shouldHide, visibleTabBarStyle])
  );
}

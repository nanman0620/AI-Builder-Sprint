import { useFocusEffect, useNavigation } from '@react-navigation/native';
import { useCallback } from 'react';

// app/(tabs)/home.tsx는 Tabs의 직접 자식 Screen이라 getParent() 없이 이 화면 자신의
// navigation.setOptions로 tabBarStyle을 바꿀 수 있다(§10). app/(tabs)/_layout.tsx는 그대로 둔다.
//
// FINALIZING·CHECK_IN_RESULT·DEADLINE_WARNING(blockingNotice)에서만 하단 탭을 숨긴다.
// homeMode가 바뀌거나 blockingNotice가 해제되면 shouldHide 값이 바뀌어 이 effect가 다시 실행되고,
// 화면이 blur되거나 unmount되면 cleanup에서 항상 원래(표시) 상태로 복원한다.
export function useHideTabBar(shouldHide: boolean) {
  const navigation = useNavigation();

  useFocusEffect(
    useCallback(() => {
      navigation.setOptions({ tabBarStyle: shouldHide ? { display: 'none' } : undefined });
      return () => {
        navigation.setOptions({ tabBarStyle: undefined });
      };
    }, [navigation, shouldHide])
  );
}

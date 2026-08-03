import { useEffect, useRef, useState } from 'react';
import { Animated, Dimensions, Easing, Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { fonts } from '@/src/constants/tokens';
import { getLogoutSheetPaddingBottom } from '@/src/features/settings/components/logout-confirm-modal-layout';

type LogoutConfirmModalProps = {
  visible: boolean;
  loading?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
};

const TEXT = '#1D1D23';
const TEXT_SECONDARY = '#85818A';
const HANDLE_COLOR = '#C4C4C4';
const LOGOUT_RED = '#EF5B5B';
const SHEET_MAX_WIDTH = 390;

const OVERLAY_FADE_MS = 200;
const SHEET_SLIDE_MS = 300;
const OFF_SCREEN_Y = Dimensions.get('window').height;

// UI-030 로그아웃 오버레이: 딤 배경 fade + 바텀 시트 slide-up. Modal 자체 animationType은 쓰지 않고
// visible이 false로 바뀐 뒤에도 닫힘 애니메이션이 끝날 때까지 isMounted로 렌더링을 유지한다.
export function LogoutConfirmModal({ visible, loading = false, onCancel, onConfirm }: LogoutConfirmModalProps) {
  const { bottom: bottomInset } = useSafeAreaInsets();
  const [isMounted, setIsMounted] = useState(visible);
  const overlayOpacity = useRef(new Animated.Value(0)).current;
  const sheetTranslateY = useRef(new Animated.Value(OFF_SCREEN_Y)).current;

  useEffect(() => {
    if (visible) {
      setIsMounted(true);
      Animated.parallel([
        Animated.timing(overlayOpacity, {
          toValue: 1,
          duration: OVERLAY_FADE_MS,
          easing: Easing.ease,
          useNativeDriver: true,
        }),
        Animated.timing(sheetTranslateY, {
          toValue: 0,
          duration: SHEET_SLIDE_MS,
          easing: Easing.ease,
          useNativeDriver: true,
        }),
      ]).start();
      return;
    }

    Animated.parallel([
      Animated.timing(overlayOpacity, {
        toValue: 0,
        duration: OVERLAY_FADE_MS,
        easing: Easing.ease,
        useNativeDriver: true,
      }),
      Animated.timing(sheetTranslateY, {
        toValue: OFF_SCREEN_Y,
        duration: SHEET_SLIDE_MS,
        easing: Easing.ease,
        useNativeDriver: true,
      }),
    ]).start(({ finished }) => {
      if (finished) {
        setIsMounted(false);
      }
    });
  }, [visible, overlayOpacity, sheetTranslateY]);

  if (!isMounted) {
    return null;
  }

  return (
    <Modal transparent visible={isMounted} animationType="none" onRequestClose={onCancel} statusBarTranslucent>
      <View style={styles.root}>
        <Animated.View style={[StyleSheet.absoluteFill, styles.overlay, { opacity: overlayOpacity }]}>
          <Pressable
            style={StyleSheet.absoluteFill}
            onPress={onCancel}
            disabled={loading}
            accessibilityRole="button"
            accessibilityLabel="닫기"
          />
        </Animated.View>
        <Animated.View style={[styles.sheetContainer, { transform: [{ translateY: sheetTranslateY }] }]}>
          <View style={[styles.sheet, { paddingBottom: getLogoutSheetPaddingBottom(bottomInset) }]}>
            <View style={styles.handle} />
            <Text style={styles.title}>로그아웃할까요?</Text>
            <Text style={styles.description}>다음에는 다시 로그인해야 해요.</Text>
            <Pressable
              style={[styles.confirmButton, loading ? styles.buttonDisabled : null]}
              onPress={onConfirm}
              disabled={loading}>
              <Text style={styles.confirmText}>로그아웃</Text>
            </Pressable>
            <Pressable style={styles.cancelButton} onPress={onCancel} disabled={loading}>
              <Text style={styles.cancelText}>취소</Text>
            </Pressable>
          </View>
        </Animated.View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  overlay: {
    backgroundColor: 'rgba(0, 0, 0, 0.4)',
  },
  sheetContainer: {
    width: '100%',
    maxWidth: SHEET_MAX_WIDTH,
    alignSelf: 'center',
  },
  sheet: {
    backgroundColor: '#FFFFFF',
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: 24,
  },
  handle: {
    width: 36,
    height: 4,
    borderRadius: 2,
    backgroundColor: HANDLE_COLOR,
    alignSelf: 'center',
    marginTop: 12,
    marginBottom: 24,
  },
  title: {
    fontSize: 20,
    fontFamily: fonts.bold,
    color: TEXT,
  },
  description: {
    marginTop: 10,
    fontSize: 14,
    fontFamily: fonts.regular,
    color: TEXT_SECONDARY,
  },
  confirmButton: {
    height: 52,
    borderRadius: 12,
    backgroundColor: LOGOUT_RED,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 28,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  confirmText: {
    fontSize: 16,
    fontFamily: fonts.bold,
    color: '#FFFFFF',
  },
  cancelButton: {
    marginTop: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
  cancelText: {
    fontSize: 14,
    fontFamily: fonts.regular,
    color: TEXT_SECONDARY,
  },
});

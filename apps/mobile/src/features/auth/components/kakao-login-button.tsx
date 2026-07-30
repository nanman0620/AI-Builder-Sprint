import { Pressable, StyleSheet } from 'react-native';
import MaterialIcons from '@expo/vector-icons/MaterialIcons';

// 저장소에 카카오 공식 로고 자산이 없어 UI-002를 참고한 노란 원형+말풍선 아이콘 근사 구현이다.
// 캡처 이미지를 크롭해 쓰지 않고 코드 컴포넌트로만 구현한다.
const KAKAO_YELLOW = '#FEE500';
const KAKAO_ICON_COLOR = '#191919';

type KakaoLoginButtonProps = {
  onPress: () => void;
  disabled?: boolean;
};

export function KakaoLoginButton({ onPress, disabled = false }: KakaoLoginButtonProps) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="카카오로 로그인"
      style={[styles.circle, disabled ? styles.disabled : null]}
      onPress={onPress}
      disabled={disabled}>
      <MaterialIcons name="chat-bubble" size={16} color={KAKAO_ICON_COLOR} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  circle: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: KAKAO_YELLOW,
    alignItems: 'center',
    justifyContent: 'center',
  },
  disabled: {
    opacity: 0.6,
  },
});

import { Image, Pressable, StyleSheet } from 'react-native';

const KAKAO_YELLOW = '#FEE500';

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
      <Image
        source={require('@/assets/brand/kakaotalk-seeklogo.png')}
        style={styles.logo}
        resizeMode="contain"
        accessible={false}
      />
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
    overflow: 'hidden',
  },
  logo: {
    width: 32,
    height: 32,
  },
  disabled: {
    opacity: 0.6,
  },
});

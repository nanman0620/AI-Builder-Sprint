import { ActivityIndicator, Pressable, StyleSheet, Text } from 'react-native';

import { colors } from '@/src/constants/tokens';

// Figma 캡처 기준 조밀한 버튼 치수(390dp 기준 뷰포트 대비 실측 근사값).
const BUTTON_HEIGHT = 46;
const BUTTON_RADIUS = 8;
const BUTTON_FONT_SIZE = 15;

type AuthSubmitButtonProps = {
  label: string;
  onPress: () => void;
  loading?: boolean;
  disabled?: boolean;
};

export function AuthSubmitButton({ label, onPress, loading = false, disabled = false }: AuthSubmitButtonProps) {
  const isDisabled = disabled || loading;

  return (
    <Pressable
      style={[styles.button, isDisabled ? styles.buttonDisabled : null]}
      onPress={onPress}
      disabled={isDisabled}>
      {loading ? <ActivityIndicator color={colors.background} /> : <Text style={styles.buttonText}>{label}</Text>}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    height: BUTTON_HEIGHT,
    backgroundColor: colors.primary,
    borderRadius: BUTTON_RADIUS,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    fontSize: BUTTON_FONT_SIZE,
    color: colors.background,
    fontWeight: '700',
  },
});

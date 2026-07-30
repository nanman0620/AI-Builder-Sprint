import { useState } from 'react';
import { StyleSheet, Text, TextInput, TouchableOpacity, View, type TextInputProps } from 'react-native';

import { colors, spacing } from '@/src/constants/tokens';
import { AuthMaterialIcon } from '@/src/features/auth/components/auth-material-icon';

type AuthTextInputProps = TextInputProps & {
  label?: string;
  error?: string | null;
  secureToggle?: boolean;
};

// Figma UI-002/003/004 캡처 기준 조밀한 치수(390dp 기준 뷰포트 대비 실측 근사값).
const INPUT_HEIGHT = 46;
const INPUT_RADIUS = 8;
const LABEL_FONT_SIZE = 13;
const INPUT_FONT_SIZE = 14;
const ERROR_FONT_SIZE = 12;

export function AuthTextInput({
  label,
  error,
  secureToggle = false,
  secureTextEntry,
  style,
  ...rest
}: AuthTextInputProps) {
  const [isVisible, setIsVisible] = useState(false);
  const resolvedSecureTextEntry = secureToggle ? !isVisible : secureTextEntry;

  return (
    <View style={styles.container}>
      {label ? <Text style={styles.label}>{label}</Text> : null}
      <View style={[styles.inputRow, error ? styles.inputRowError : null]}>
        <TextInput
          style={[styles.input, style]}
          placeholderTextColor={colors.textSecondary}
          secureTextEntry={resolvedSecureTextEntry}
          {...rest}
        />
        {secureToggle ? (
          <TouchableOpacity
            onPress={() => setIsVisible((prev) => !prev)}
            hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
            <AuthMaterialIcon
              name={isVisible ? 'visibility' : 'visibility-off'}
              size={16}
              color={colors.textSecondary}
            />
          </TouchableOpacity>
        ) : null}
      </View>
      {error ? <Text style={styles.errorText}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    marginBottom: spacing.md,
  },
  label: {
    fontSize: LABEL_FONT_SIZE,
    fontWeight: '700',
    color: colors.text,
    marginBottom: 6,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    height: INPUT_HEIGHT,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: INPUT_RADIUS,
    paddingHorizontal: 14,
  },
  inputRowError: {
    borderColor: colors.error,
    backgroundColor: colors.primarySoft,
  },
  input: {
    flex: 1,
    fontSize: INPUT_FONT_SIZE,
    color: colors.text,
    paddingVertical: 0,
  },
  errorText: {
    fontSize: ERROR_FONT_SIZE,
    color: colors.error,
    marginTop: 4,
  },
});

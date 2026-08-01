import { Ionicons } from '@expo/vector-icons';
import { Pressable, StyleSheet, TextInput, View } from 'react-native';

import { PLAN_COMPOSER_BOTTOM_OFFSET } from '@/src/constants/tab-bar';
import { colors, fonts, spacing } from '@/src/constants/tokens';

type MessageInputProps = {
  value: string;
  onChangeText: (text: string) => void;
  onSubmit: () => void;
  placeholder?: string;
  disabled?: boolean;
};

export function MessageInput({
  value,
  onChangeText,
  onSubmit,
  placeholder = '메세지를 입력하세요',
  disabled = false,
}: MessageInputProps) {
  const canSubmit = !disabled && value.trim().length > 0;

  return (
    <View style={styles.container}>
      <TextInput
        style={styles.input}
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.textSecondary}
        editable={!disabled}
        multiline
      />
      <Pressable
        style={[styles.sendButton, !canSubmit && styles.sendButtonDisabled]}
        onPress={onSubmit}
        disabled={!canSubmit}
        accessibilityRole="button"
        accessibilityLabel="메시지 보내기">
        <Ionicons name="send" size={18} color="#FFFFFF" />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    gap: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.background,
    marginBottom: PLAN_COMPOSER_BOTTOM_OFFSET,
  },
  input: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 20,
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    minHeight: 40,
    maxHeight: 120,
    color: colors.text,
    fontFamily: fonts.regular,
    fontSize: 14,
    lineHeight: 18,
  },
  sendButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendButtonDisabled: {
    opacity: 0.4,
  },
});

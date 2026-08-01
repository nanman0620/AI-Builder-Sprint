import { Ionicons } from '@expo/vector-icons';
import { Pressable, StyleSheet, TextInput, View } from 'react-native';

import { PLAN_COMPOSER_BOTTOM_OFFSET } from '@/src/constants/tab-bar';
import { colors, spacing } from '@/src/constants/tokens';

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
        numberOfLines={1}
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
    marginBottom: PLAN_COMPOSER_BOTTOM_OFFSET - 4,
  },
  input: {
    flex: 1,
    minHeight: 40,
    maxHeight: 120,

    fontSize: 16,
    lineHeight: 20,

    textAlignVertical: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,

    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 24,
    color: colors.text,
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

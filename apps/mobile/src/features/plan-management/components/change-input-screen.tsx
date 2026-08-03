import { useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from 'react-native';

import { colors, spacing, typography } from '@/src/constants/tokens';

import { buildConversationTimeline } from '../logic';
import type { SolarRequest } from '../types';
import { ConversationTimeline } from './conversation-timeline';
import { MessageInput } from './message-input';
import { PlanKeyboardLayout } from './plan-keyboard-layout';

type ChangeInputScreenProps = {
  request: SolarRequest;
  isSubmitting: boolean;
  actionError: string | null;
  onSendMessage: (message: string) => void;
};

export function ChangeInputScreen({ request, isSubmitting, actionError, onSendMessage }: ChangeInputScreenProps) {
  const [value, setValue] = useState('');
  const timeline = buildConversationTimeline(request);

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed || isSubmitting) return;
    onSendMessage(trimmed);
    setValue('');
  };

  return (
    <PlanKeyboardLayout>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <View style={styles.messages}>
          <ConversationTimeline entries={timeline} />
        </View>
        {isSubmitting ? (
          <View style={styles.loading}>
            <ActivityIndicator size="small" color={colors.primary} />
            <Text style={styles.loadingText}>변경 내용을 분석하고 있어요…</Text>
          </View>
        ) : null}
        {actionError ? <Text style={styles.error}>{actionError}</Text> : null}
      </ScrollView>
      <MessageInput
        value={value}
        onChangeText={setValue}
        onSubmit={handleSubmit}
        placeholder={request.inputPlaceholder ?? '추가하거나 수정할 내용을 입력해 주세요.'}
        disabled={isSubmitting}
      />
    </PlanKeyboardLayout>
  );
}

const styles = StyleSheet.create({
  content: {
    padding: spacing.lg,
  },
  messages: {
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  loading: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  loadingText: {
    ...typography.caption,
    color: colors.textSecondary,
  },
  error: {
    ...typography.caption,
    color: colors.error,
    marginTop: spacing.md,
  },
});

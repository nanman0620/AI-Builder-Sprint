import { useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, View } from 'react-native';

import { colors, spacing, typography } from '@/src/constants/tokens';

import type { SolarRequest } from '../types';
import { ChatMessageBubble } from './chat-message-bubble';
import { MessageInput } from './message-input';
import { RequestItemCard } from './request-item-card';

type ChangeInputScreenProps = {
  request: SolarRequest;
  isSubmitting: boolean;
  actionError: string | null;
  onSendMessage: (message: string) => void;
};

export function ChangeInputScreen({ request, isSubmitting, actionError, onSendMessage }: ChangeInputScreenProps) {
  const [value, setValue] = useState('');
  const sortedItems = [...request.requestItems].sort((a, b) => a.itemOrder - b.itemOrder);
  const sortedMessages = [...request.messages].sort((a, b) => a.sequenceNo - b.sequenceNo);

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed || isSubmitting) return;
    onSendMessage(trimmed);
    setValue('');
  };

  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        {sortedItems.map((item) => (
          <RequestItemCard key={item.id} item={item} highlighted={item.id === request.pendingItemId} />
        ))}
        <View style={styles.messages}>
          {sortedMessages.map((message) => (
            <ChatMessageBubble key={message.id} message={message} />
          ))}
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
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: {
    flex: 1,
    backgroundColor: colors.background,
  },
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

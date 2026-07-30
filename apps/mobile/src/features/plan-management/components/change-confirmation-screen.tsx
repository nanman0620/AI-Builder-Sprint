import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { colors, spacing, typography } from '@/src/constants/tokens';

import type { DecisionOption, SolarRequest } from '../types';
import { ChatMessageBubble } from './chat-message-bubble';
import { RequestItemCard } from './request-item-card';

type ChangeConfirmationScreenProps = {
  request: SolarRequest;
  isSubmitting: boolean;
  actionError: string | null;
  onDecision: (decision: DecisionOption['value']) => void;
};

export function ChangeConfirmationScreen({
  request,
  isSubmitting,
  actionError,
  onDecision,
}: ChangeConfirmationScreenProps) {
  const sortedItems = [...request.requestItems].sort((a, b) => a.itemOrder - b.itemOrder);
  const sortedMessages = [...request.messages].sort((a, b) => a.sequenceNo - b.sequenceNo);
  const prompt = request.decisionPrompt;

  return (
    <ScrollView contentContainerStyle={styles.content}>
      {sortedItems.map((item) => (
        <RequestItemCard key={item.id} item={item} />
      ))}
      {sortedItems.length > 0 ? (
        <Text style={styles.guidance}>모호한 항목은 따로 질문하고 나머지는 이대로 확정해요.</Text>
      ) : null}
      <View style={styles.messages}>
        {sortedMessages.map((message) => (
          <ChatMessageBubble key={message.id} message={message} />
        ))}
      </View>
      <Text style={styles.prompt}>{prompt?.message ?? '수정하거나 추가할 내용이 있나요?'}</Text>
      <View style={styles.options}>
        {prompt?.options.map((option) => (
          <Pressable
            key={option.value}
            style={[styles.option, isSubmitting && styles.disabled]}
            onPress={() => onDecision(option.value)}
            disabled={isSubmitting}>
            <Text style={styles.optionText}>{option.label}</Text>
          </Pressable>
        ))}
      </View>
      {isSubmitting ? <ActivityIndicator color={colors.primary} style={styles.loading} /> : null}
      {actionError ? <Text style={styles.error}>{actionError}</Text> : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: {
    padding: spacing.lg,
    backgroundColor: colors.background,
    flexGrow: 1,
  },
  guidance: {
    ...typography.caption,
    color: colors.textSecondary,
    marginBottom: spacing.lg,
  },
  messages: {
    gap: spacing.sm,
  },
  prompt: {
    ...typography.body,
    color: colors.text,
    fontWeight: '600',
    backgroundColor: colors.primarySoft,
    borderRadius: 12,
    padding: spacing.md,
    marginTop: spacing.md,
  },
  options: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  option: {
    flex: 1,
    borderColor: colors.primary,
    borderWidth: 1,
    borderRadius: 10,
    padding: spacing.sm,
  },
  optionText: {
    ...typography.body,
    color: colors.primary,
    textAlign: 'center',
  },
  disabled: {
    opacity: 0.5,
  },
  loading: {
    marginTop: spacing.md,
  },
  error: {
    ...typography.caption,
    color: colors.error,
    marginTop: spacing.md,
  },
});

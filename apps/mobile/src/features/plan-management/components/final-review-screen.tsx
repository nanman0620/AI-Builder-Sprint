import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { ErrorView } from '@/src/components/common/error-view';
import { colors, fonts, spacing, typography } from '@/src/constants/tokens';

import { getVisibleConversationMessages } from '../logic';
import type { SolarRequest } from '../types';
import { ChatMessageBubble } from './chat-message-bubble';
import { RequestItemCard } from './request-item-card';

type FinalReviewScreenProps = {
  request: SolarRequest | null;
  isSubmitting: boolean;
  actionError: string | null;
  onReload: () => void;
  onReopen: () => void;
  onExecute: () => void;
};

export function FinalReviewScreen({
  request,
  isSubmitting,
  actionError,
  onReload,
  onReopen,
  onExecute,
}: FinalReviewScreenProps) {
  const sortedItems = request ? [...request.requestItems].sort((a, b) => a.itemOrder - b.itemOrder) : [];
  const sortedMessages = request ? getVisibleConversationMessages(request) : [];

  if (!request || sortedItems.length === 0) {
    return <ErrorView onRetry={onReload} />;
  }

  return (
    <View style={styles.container}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>할 일 및 고정 일정 등록</Text>
        <View style={styles.messages}>
          {sortedMessages.map((message) => (
            <ChatMessageBubble key={message.id} message={message} />
          ))}
        </View>
        {sortedItems.map((item) => (
          <RequestItemCard key={item.id} item={item} />
        ))}
        {actionError ? <Text style={styles.error}>{actionError}</Text> : null}
      </ScrollView>
      <View style={styles.actions}>
        <Pressable
          style={[styles.button, styles.secondaryButton, isSubmitting && styles.disabled]}
          onPress={onReopen}
          disabled={isSubmitting}>
          <Text style={styles.secondaryButtonText}>수정</Text>
        </Pressable>
        <Pressable
          style={[styles.button, styles.primaryButton, isSubmitting && styles.disabled]}
          disabled={isSubmitting}
          onPress={onExecute}>
          <Text style={styles.primaryButtonText}>{isSubmitting ? '등록 중...' : '모두 등록'}</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  content: {
    padding: spacing.lg,
  },
  title: {
    ...typography.title,
    color: colors.text,
    marginBottom: spacing.lg,
  },
  messages: {
    gap: spacing.sm,
    marginBottom: spacing.lg,
  },
  error: {
    ...typography.caption,
    color: colors.error,
    marginTop: spacing.md,
  },
  actions: {
    flexDirection: 'row',
    gap: spacing.md,
    padding: spacing.lg,
    borderTopWidth: 1,
    paddingBottom: spacing.xl +10,
    borderTopColor: colors.border,
  },
  button: {
    flex: 1,
    borderRadius: 12,
    paddingVertical: spacing.md,
  },
  secondaryButton: {
    borderWidth: 1,
    borderColor: colors.textSecondary,
  },
  secondaryButtonText: {
    ...typography.body,
    color: colors.textSecondary,
    textAlign: 'center',
    fontFamily: fonts.bold,
  },
  primaryButton: {
    backgroundColor: colors.primary,
  },
  primaryButtonText: {
    ...typography.body,
    color: colors.background,
    textAlign: 'center',
    fontFamily: fonts.bold,
  },
  disabled: {
    opacity: 0.5,
  },
});

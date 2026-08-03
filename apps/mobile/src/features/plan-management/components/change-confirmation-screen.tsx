import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { colors, spacing, typography } from '@/src/constants/tokens';

import { buildConversationTimeline } from '../logic';
import type { DecisionOption, SolarRequest } from '../types';
import { ConversationTimeline } from './conversation-timeline';

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
  const timeline = buildConversationTimeline(request);
  const prompt = request.decisionPrompt;

  return (
    <ScrollView contentContainerStyle={styles.content}>
      <ConversationTimeline entries={timeline} />
      {prompt ? <View style={styles.options}>
        {prompt.options.map((option) => (
          <Pressable
            key={option.value}
            style={[styles.option, isSubmitting && styles.disabled]}
            onPress={() => onDecision(option.value)}
            disabled={isSubmitting}>
            <Text style={styles.optionText}>{option.label}</Text>
          </Pressable>
        ))}
      </View> : null}
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

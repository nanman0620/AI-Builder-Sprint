import { LinearGradient } from 'expo-linear-gradient';
import { StyleSheet, Text, View } from 'react-native';

import { colors, spacing, typography } from '@/src/constants/tokens';

import type { ChatMessage } from '../types';

type ChatMessageBubbleProps = {
  message: ChatMessage;
};

export function ChatMessageBubble({ message }: ChatMessageBubbleProps) {
  const isUser = message.role === 'USER';

  return (
    <View style={[styles.row, isUser ? styles.rowRight : styles.rowLeft]}>
      {isUser ? (
        <LinearGradient
          colors={['#A83DE2', '#D279FE']}
          start={{ x: 0, y: 0.5 }}
          end={{ x: 1, y: 0.5 }}
          style={styles.bubble}>
          <Text style={[styles.text, styles.textUser]}>{message.content}</Text>
        </LinearGradient>
      ) : (
        <View style={[styles.bubble, styles.bubbleAssistant]}>
          <Text style={[styles.text, styles.textAssistant]}>{message.content}</Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    marginBottom: spacing.sm,
  },
  rowLeft: {
    justifyContent: 'flex-start',
  },
  rowRight: {
    justifyContent: 'flex-end',
  },
  bubble: {
    maxWidth: '80%',
    borderRadius: 16,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  bubbleAssistant: {
    backgroundColor: colors.primarySoft,
  },
  text: {
    ...typography.body,
  },
  textAssistant: {
    color: colors.text,
  },
  textUser: {
    color: '#FFFFFF',
  },
});

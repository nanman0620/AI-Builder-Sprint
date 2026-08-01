import { StyleSheet, View } from 'react-native';

import { spacing } from '@/src/constants/tokens';

import type { ConversationTimelineEntry } from '../types';
import { ChatMessageBubble } from './chat-message-bubble';
import { RequestItemCard } from './request-item-card';

type ConversationTimelineProps = {
  entries: ConversationTimelineEntry[];
};

export function ConversationTimeline({ entries }: ConversationTimelineProps) {
  return (
    <View style={styles.timeline}>
      {entries.map((entry) => {
        if (entry.type === 'MESSAGE') {
          return <ChatMessageBubble key={entry.id} message={entry.message} />;
        }
        if (entry.type === 'REQUEST_ITEM_SNAPSHOT') {
          return <RequestItemCard key={entry.id} item={entry.snapshot} />;
        }
        if (entry.type === 'LEGACY_CURRENT_REQUEST_ITEM') {
          return <RequestItemCard key={entry.id} item={entry.item} />;
        }
        return (
          <ChatMessageBubble
            key={entry.id}
            message={{
              id: entry.id,
              role: 'ASSISTANT',
              kind: 'QUESTION',
              content: entry.message,
              sequenceNo: Number.MAX_SAFE_INTEGER,
              createdAt: '',
              metadata: { promptType: 'CHANGE_CONFIRMATION' },
            }}
          />
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  timeline: {
    gap: spacing.sm,
  },
});

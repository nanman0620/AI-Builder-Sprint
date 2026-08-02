import { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { colors, spacing, typography } from '@/src/constants/tokens';

import { buildConversationTimeline } from '../logic';
import type { SolarRequest } from '../types';
import { ConversationTimeline } from './conversation-timeline';
import { MessageInput } from './message-input';
import { PlanKeyboardLayout } from './plan-keyboard-layout';

type CollectingScreenProps = {
  request: SolarRequest;
  isSubmitting: boolean;
  actionError: string | null;
  onSendMessage: (message: string) => void;
};

// COLLECTING은 최초 분석 결과 카드(UI-014)와 질문·답변·재질문(UI-015)이 모두 같은
// 화면·같은 데이터(messages/requestItems/currentQuestion/quickReplies/inputPlaceholder/
// pendingItemId)의 variant이므로 별도 Route나 하위 상태 없이 하나의 컴포넌트로 그린다.
//
// 팀 최종 정책: COLLECTING 중간 질문 답변은 항상 텍스트 입력으로만 받는다("잘 모르겠어요"
// 포함). quickReplies는 응답 DTO에는 남아 있지만 이 화면에서는 렌더링하지 않는다.
// (CHANGE_CONFIRMATION의 YES/NO 결정 버튼은 별도 정책이며 FE-04에서 구현한다.)
export function CollectingScreen({ request, isSubmitting, actionError, onSendMessage }: CollectingScreenProps) {
  const [value, setValue] = useState('');
  const scrollViewRef = useRef<ScrollView>(null);

  const timeline = buildConversationTimeline(request);

  useEffect(() => {
    scrollViewRef.current?.scrollToEnd({ animated: true });
  }, [timeline.length]);

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed || isSubmitting) return;
    onSendMessage(trimmed);
    setValue('');
  };

  return (
    <PlanKeyboardLayout>
      <ScrollView
        ref={scrollViewRef}
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled">
        <View style={styles.messages}>
          <ConversationTimeline entries={timeline} />
          {isSubmitting && (
            <View style={styles.typingRow}>
              <ActivityIndicator size="small" color={colors.primary} />
              <Text style={styles.typingText}>답변을 분석하고 있어요…</Text>
            </View>
          )}
        </View>
        {actionError && <Text style={styles.actionError}>{actionError}</Text>}
      </ScrollView>
      <MessageInput
        value={value}
        onChangeText={setValue}
        onSubmit={handleSubmit}
        placeholder={request.inputPlaceholder ?? undefined}
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
  },
  typingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  typingText: {
    ...typography.caption,
    color: colors.textSecondary,
  },
  actionError: {
    ...typography.caption,
    color: colors.error,
    marginTop: spacing.md,
  },
});

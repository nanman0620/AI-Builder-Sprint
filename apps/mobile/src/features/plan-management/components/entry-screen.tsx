import { useState } from 'react';
import { Image, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { colors, spacing, typography } from '@/src/constants/tokens';

import { MessageInput } from './message-input';

const mascotReading = require('@/assets/brand/mascot-reading.png');

type EntryScreenProps = {
  title: string;
  examples: string[];
  isSubmitting: boolean;
  onSubmit: (message: string) => void;
};

// NEW_CYCLE_ENTRY(UI-012)와 ACTIVE_CYCLE_ENTRY(UI-013)는 제목·예시 문구만 다르고
// 레이아웃은 완전히 같은 화면이라 하나의 컴포넌트로 공유한다.
export function EntryScreen({ title, examples, isSubmitting, onSubmit }: EntryScreenProps) {
  const [value, setValue] = useState('');

  const handleExamplePress = (example: string) => {
    setValue((prev) => (prev.length > 0 ? `${prev}\n${example}` : example));
  };

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed || isSubmitting) return;
    onSubmit(trimmed);
    setValue('');
  };

  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Image source={mascotReading} style={styles.mascot} resizeMode="contain" />
        <Text style={styles.title}>{title}</Text>
        <Text style={styles.subtitle}>해야 할 일과 고정 일정을 다음과 같이 말해주세요.</Text>
        <View style={styles.examples}>
          {examples.map((example) => (
            <Pressable
              key={example}
              style={styles.exampleChip}
              disabled={isSubmitting}
              onPress={() => handleExamplePress(example)}>
              <Text style={styles.exampleText}>{example}</Text>
            </Pressable>
          ))}
        </View>
        <Text style={styles.hint}>대화 기록은 이 탭을 벗어나면 사라져요</Text>
      </ScrollView>
      <MessageInput value={value} onChangeText={setValue} onSubmit={handleSubmit} disabled={isSubmitting} />
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
  mascot: {
    width: 96,
    height: 96,
    marginBottom: spacing.lg,
  },
  title: {
    ...typography.title,
    color: colors.text,
    marginBottom: spacing.sm,
  },
  subtitle: {
    ...typography.body,
    color: colors.textSecondary,
    marginBottom: spacing.md,
  },
  examples: {
    gap: spacing.sm,
  },
  exampleChip: {
    borderWidth: 1,
    borderColor: colors.primary,
    borderRadius: 20,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    alignSelf: 'flex-start',
  },
  exampleText: {
    ...typography.body,
    color: colors.primary,
  },
  hint: {
    ...typography.caption,
    color: colors.textSecondary,
    marginTop: spacing.md,
  },
});

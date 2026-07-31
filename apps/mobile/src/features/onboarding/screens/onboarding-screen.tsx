import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Image, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { colors } from '@/src/constants/tokens';
import { putOnboarding } from '@/src/features/onboarding/api/onboarding';
import { validateNickname } from '@/src/features/onboarding/validation';
import { ApiClientError } from '@/src/services/api/client';

const NETWORK_ERROR_MESSAGE = '정보를 불러오지 못했어요.\n잠시 후 다시 시도해 주세요.';

export function OnboardingScreen() {
  const router = useRouter();

  const [nickname, setNickname] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  function handleChangeNickname(value: string) {
    setNickname(value);
    if (error) {
      setError(validateNickname(value));
    }
  }

  async function handleSubmit() {
    if (isSubmitting) {
      return;
    }

    const validationError = validateNickname(nickname);
    if (validationError) {
      setError(validationError);
      return;
    }

    setError(null);
    setIsSubmitting(true);
    try {
      await putOnboarding(nickname.trim());
      router.replace('/');
    } catch (caughtError) {
      if (caughtError instanceof ApiClientError && caughtError.code === 'INVALID_NICKNAME') {
        setError(caughtError.message);
      } else {
        setError(NETWORK_ERROR_MESSAGE);
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <SafeAreaView style={styles.safeArea} edges={['top', 'bottom']}>
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.scrollContent} keyboardShouldPersistTaps="handled">
          <View style={styles.content}>
            {/* 마스코트 -> 제목 -> 입력 -> 버튼을 하나의 그룹으로 묶어 화면 중앙 부근에 배치한다. */}
            <View style={styles.group}>
              <Image
                source={require('@/assets/brand/mascot-default.png')}
                style={styles.mascot}
                resizeMode="contain"
              />

              <Text style={styles.title}>
                <Text style={styles.titleHighlight}>이음</Text>에서 어떻게 불러드릴까요?
              </Text>

              <TextInput
                style={[styles.input, error ? styles.inputError : null]}
                placeholder="닉네임을 입력해주세요"
                placeholderTextColor={colors.textSecondary}
                value={nickname}
                onChangeText={handleChangeNickname}
                editable={!isSubmitting}
              />
              {error ? <Text style={styles.errorText}>{error}</Text> : null}

              <Pressable
                style={[styles.button, isSubmitting ? styles.buttonDisabled : null]}
                onPress={handleSubmit}
                disabled={isSubmitting}>
                <Text style={styles.buttonText}>저장</Text>
              </Pressable>
            </View>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const CONTENT_MAX_WIDTH = 400;
const MASCOT_WIDTH = 225;
const MASCOT_HEIGHT = Math.round((MASCOT_WIDTH * 534) / 711);

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: colors.background,
  },
  flex: {
    flex: 1,
  },
  scrollContent: {
    flexGrow: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 24,
  },
  content: {
    width: '100%',
    maxWidth: CONTENT_MAX_WIDTH,
    paddingHorizontal: 20,
  },
  group: {
    width: '100%',
  },
  mascot: {
    width: MASCOT_WIDTH,
    height: MASCOT_HEIGHT,
    alignSelf: 'center',
    marginBottom: 24,
  },
  title: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.text,
    textAlign: 'center',
    marginBottom: 24,
  },
  titleHighlight: {
    color: colors.primary,
  },
  input: {
    height: 46,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingHorizontal: 14,
    fontSize: 14,
    color: colors.text,
    marginBottom: 10,
  },
  inputError: {
    borderColor: colors.error,
    backgroundColor: colors.primarySoft,
  },
  errorText: {
    fontSize: 12,
    color: colors.error,
    marginBottom: 10,
  },
  button: {
    height: 46,
    backgroundColor: colors.primary,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    fontSize: 15,
    color: colors.background,
    fontWeight: '700',
  },
});

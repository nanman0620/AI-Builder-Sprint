import { useState } from 'react';
import { Image, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import MaterialIcons from '@expo/vector-icons/MaterialIcons';

import { colors } from '@/src/constants/tokens';
import { AuthSubmitButton } from '@/src/features/auth/components/auth-submit-button';
import { AuthTextInput } from '@/src/features/auth/components/auth-text-input';
import { toSignUpErrorMessage, AUTH_NETWORK_ERROR_MESSAGE } from '@/src/features/auth/errors';
import { signUpWithEmail } from '@/src/features/auth/services/auth-service';
import {
  MIN_PASSWORD_LENGTH,
  validateEmail,
  validatePasswordConfirm,
  validateSignUpPassword,
  validateTerms,
} from '@/src/features/auth/validation';

export function SignUpScreen() {
  const router = useRouter();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [agreedToTerms, setAgreedToTerms] = useState(false);

  const [emailError, setEmailError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [passwordConfirmError, setPasswordConfirmError] = useState<string | null>(null);
  const [termsError, setTermsError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const [isSubmitting, setIsSubmitting] = useState(false);

  function handleChangeEmail(value: string) {
    setEmail(value);
    if (emailError) {
      setEmailError(validateEmail(value));
    }
    if (formError) {
      setFormError(null);
    }
  }

  function handleChangePassword(value: string) {
    setPassword(value);
    if (passwordError) {
      setPasswordError(validateSignUpPassword(value));
    }
    if (passwordConfirmError) {
      setPasswordConfirmError(validatePasswordConfirm(value, passwordConfirm));
    }
    if (formError) {
      setFormError(null);
    }
  }

  function handleChangePasswordConfirm(value: string) {
    setPasswordConfirm(value);
    if (passwordConfirmError) {
      setPasswordConfirmError(validatePasswordConfirm(password, value));
    }
    if (formError) {
      setFormError(null);
    }
  }

  function handleToggleTerms() {
    setAgreedToTerms((prev) => {
      const next = !prev;
      if (termsError) {
        setTermsError(validateTerms(next));
      }
      return next;
    });
    if (formError) {
      setFormError(null);
    }
  }

  function handleBack() {
    router.back();
  }

  async function handleSubmit() {
    if (isSubmitting) {
      return;
    }

    const nextEmailError = validateEmail(email);
    const nextPasswordError = validateSignUpPassword(password);
    const nextPasswordConfirmError = validatePasswordConfirm(password, passwordConfirm);
    const nextTermsError = validateTerms(agreedToTerms);

    setEmailError(nextEmailError);
    setPasswordError(nextPasswordError);
    setPasswordConfirmError(nextPasswordConfirmError);
    setTermsError(nextTermsError);

    if (nextEmailError || nextPasswordError || nextPasswordConfirmError || nextTermsError) {
      return;
    }

    setFormError(null);
    setIsSubmitting(true);
    try {
      const result = await signUpWithEmail(email.trim(), password);

      if (result.status === 'success') {
        router.replace('/(auth)/onboarding');
        return;
      }

      if (result.status === 'no-session') {
        // MVP는 이메일 인증을 사용하지 않으므로 session이 없으면 설정 확인이 필요한 상황이다.
        // 개발자용 문구 대신 표준 공통 오류로 안내하고 온보딩으로 이동하지 않는다.
        setFormError(AUTH_NETWORK_ERROR_MESSAGE);
        return;
      }

      const target = toSignUpErrorMessage(result.error);
      if (target.field === 'email') {
        setEmailError(target.message);
      } else if (target.field === 'password') {
        setPasswordError(target.message);
      } else {
        setFormError(target.message);
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
            <View style={styles.header}>
              <Pressable onPress={handleBack} hitSlop={12} disabled={isSubmitting}>
                <MaterialIcons name="arrow-back" size={22} color={colors.text} />
              </Pressable>
              <Text style={styles.headerTitle}>회원가입</Text>
              <View style={styles.headerSpacer} />
            </View>

            <Image
              source={require('@/assets/brand/eum-logo.png')}
              style={styles.logo}
              resizeMode="contain"
            />

            <AuthTextInput
              label="이메일"
              placeholder="이메일을 입력하세요"
              autoCapitalize="none"
              keyboardType="email-address"
              value={email}
              onChangeText={handleChangeEmail}
              error={emailError}
              editable={!isSubmitting}
            />

            <AuthTextInput
              label="비밀번호"
              placeholder={`${MIN_PASSWORD_LENGTH}자 이상의 비밀번호를 입력하세요`}
              secureToggle
              value={password}
              onChangeText={handleChangePassword}
              error={passwordError}
              editable={!isSubmitting}
            />

            <AuthTextInput
              label="비밀번호 확인"
              placeholder="비밀번호를 한 번 더 입력하세요"
              secureToggle
              value={passwordConfirm}
              onChangeText={handleChangePasswordConfirm}
              error={passwordConfirmError}
              editable={!isSubmitting}
            />

            <Pressable style={styles.termsRow} onPress={handleToggleTerms} disabled={isSubmitting}>
              <MaterialIcons
                name={agreedToTerms ? 'check-box' : 'check-box-outline-blank'}
                size={20}
                color={agreedToTerms ? colors.primary : colors.textSecondary}
              />
              <Text style={styles.termsText}>서비스 이용 약관에 동의합니다.</Text>
            </Pressable>
            {termsError ? <Text style={styles.termsErrorText}>{termsError}</Text> : null}

            {formError ? <Text style={styles.formErrorText}>{formError}</Text> : null}

            <AuthSubmitButton label="가입하기" onPress={handleSubmit} loading={isSubmitting} />
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const CONTENT_MAX_WIDTH = 400;
// apps/mobile/assets/brand/eum-logo.png 원본 픽셀 비율(273x216)을 그대로 사용해 찌그러짐을 방지한다.
const LOGO_WIDTH = 90;
const LOGO_HEIGHT = Math.round((LOGO_WIDTH * 216) / 273);

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
    paddingVertical: 16,
  },
  content: {
    width: '100%',
    maxWidth: CONTENT_MAX_WIDTH,
    paddingHorizontal: 20,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 16,
  },
  headerTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.text,
  },
  headerSpacer: {
    width: 22,
  },
  logo: {
    alignSelf: 'center',
    width: LOGO_WIDTH,
    height: LOGO_HEIGHT,
    marginBottom: 16,
  },
  termsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 8,
    marginBottom: 14,
  },
  termsText: {
    fontSize: 13,
    color: colors.text,
    marginLeft: 8,
  },
  termsErrorText: {
    fontSize: 12,
    color: colors.error,
    marginBottom: 12,
  },
  formErrorText: {
    fontSize: 12,
    color: colors.error,
    marginBottom: 12,
    textAlign: 'center',
  },
});

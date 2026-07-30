import { useState } from 'react';
import { Alert, Image, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';

import { colors } from '@/src/constants/tokens';
import { AuthSubmitButton } from '@/src/features/auth/components/auth-submit-button';
import { AuthTextInput } from '@/src/features/auth/components/auth-text-input';
import { KakaoLoginButton } from '@/src/features/auth/components/kakao-login-button';
import { toLoginErrorMessage, AUTH_NETWORK_ERROR_MESSAGE } from '@/src/features/auth/errors';
import { signInWithEmail, signInWithKakao } from '@/src/features/auth/services/auth-service';
import { validateEmail, validateLoginPassword } from '@/src/features/auth/validation';

export function LoginScreen() {
  const router = useRouter();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [emailError, setEmailError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  function handleChangeEmail(value: string) {
    setEmail(value);
    if (emailError) {
      setEmailError(validateEmail(value));
    }
    if (authError) {
      setAuthError(null);
    }
  }

  function handleChangePassword(value: string) {
    setPassword(value);
    if (passwordError) {
      setPasswordError(validateLoginPassword(value));
    }
    if (authError) {
      setAuthError(null);
    }
  }

  async function handleSubmit() {
    if (isSubmitting) {
      return;
    }

    const nextEmailError = validateEmail(email);
    const nextPasswordError = validateLoginPassword(password);
    setEmailError(nextEmailError);
    setPasswordError(nextPasswordError);

    if (nextEmailError || nextPasswordError) {
      return;
    }

    setAuthError(null);
    setIsSubmitting(true);
    try {
      const result = await signInWithEmail(email.trim(), password);
      if (result.status === 'success') {
        router.replace('/');
        return;
      }
      setAuthError(toLoginErrorMessage(result.error));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleKakaoPress() {
    if (isSubmitting) {
      return;
    }

    setIsSubmitting(true);
    try {
      const result = await signInWithKakao();
      if (result.status === 'success') {
        router.replace('/');
        return;
      }
      if (result.status === 'error') {
        setAuthError(AUTH_NETWORK_ERROR_MESSAGE);
      }
      // cancelled: 사용자가 인증창을 취소·닫은 경우이므로 오류 없이 로그인 화면을 유지한다.
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleForgotPassword() {
    Alert.alert('준비 중', '비밀번호 찾기 기능은 아직 준비 중이에요.');
  }

  function handleGoToSignUp() {
    if (isSubmitting) {
      return;
    }
    router.push('/(auth)/sign-up');
  }

  return (
    <SafeAreaView style={styles.safeArea} edges={['bottom']}>
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.scrollContent} keyboardShouldPersistTaps="handled">
          <View style={styles.frame}>
            {/* UI-002 상단의 보라색 곡선 히어로 배경.
                가운데가 깊고 양끝으로 갈수록 얕아지는 곡선을 재현하기 위해,
                화면보다 훨씬 큰 원(지름 1040)의 아랫부분만 보이도록 배치한다.
                expo-linear-gradient가 없어 그라디언트 대신 단색으로 근사한다. */}
            <View style={styles.hero}>
              <View style={styles.heroCircle} />
              <Image
                source={require('@/assets/brand/mascot-default.png')}
                style={styles.mascot}
                resizeMode="contain"
              />
            </View>

            <View style={styles.formArea}>
              <Text style={styles.heading}>
                오늘의 나에게 맞춰 이어지는 계획,{'\n'}
                <Text style={styles.headingHighlight}>이음</Text>과 지금 시작해 볼까요?
              </Text>

              <Text style={styles.title}>로그인</Text>

              <AuthTextInput
                placeholder="이메일을 입력하세요"
                autoCapitalize="none"
                keyboardType="email-address"
                value={email}
                onChangeText={handleChangeEmail}
                error={emailError}
                editable={!isSubmitting}
              />

              <AuthTextInput
                placeholder="비밀번호를 입력하세요"
                secureToggle
                value={password}
                onChangeText={handleChangePassword}
                error={passwordError ?? authError}
                editable={!isSubmitting}
              />

              <View style={styles.linkRow}>
                <Text style={styles.link} onPress={handleGoToSignUp}>
                  회원가입
                </Text>
                <Text style={styles.link} onPress={handleForgotPassword}>
                  비밀번호 찾기
                </Text>
              </View>

              <AuthSubmitButton label="이메일로 로그인" onPress={handleSubmit} loading={isSubmitting} />

              <View style={styles.dividerRow}>
                <View style={styles.dividerLine} />
                <Text style={styles.dividerText}>간편로그인</Text>
                <View style={styles.dividerLine} />
              </View>

              <View style={styles.kakaoRow}>
                <KakaoLoginButton onPress={handleKakaoPress} disabled={isSubmitting} />
              </View>
            </View>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const CONTENT_MAX_WIDTH = 400;
const HALF_WIDTH = CONTENT_MAX_WIDTH / 2;
// UI-002의 그라디언트(연보라 -> 보라)를 단색으로 근사한 값.
const HERO_BACKGROUND = '#C9A6F5';
const HERO_HEIGHT = 190;
// 화면 중앙에서 가장 깊고(위 값과 동일) 좌우 끝에서 가장 얕은(EDGE_DEPTH) 완만한 곡선.
const EDGE_DEPTH = 150;
const SAG = HERO_HEIGHT - EDGE_DEPTH;
const CIRCLE_RADIUS = (HALF_WIDTH * HALF_WIDTH + SAG * SAG) / (2 * SAG);
const CIRCLE_DIAMETER = CIRCLE_RADIUS * 2;
const CIRCLE_LEFT = HALF_WIDTH - CIRCLE_RADIUS;
const CIRCLE_TOP = HERO_HEIGHT - CIRCLE_RADIUS - CIRCLE_RADIUS;
const MASCOT_WIDTH = 80;
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
  },
  frame: {
    width: '100%',
    maxWidth: CONTENT_MAX_WIDTH,
  },
  hero: {
    width: '100%',
    height: HERO_HEIGHT,
    overflow: 'hidden',
    backgroundColor: colors.background,
    alignItems: 'center',
    justifyContent: 'center',
  },
  heroCircle: {
    position: 'absolute',
    left: CIRCLE_LEFT,
    top: CIRCLE_TOP,
    width: CIRCLE_DIAMETER,
    height: CIRCLE_DIAMETER,
    borderRadius: CIRCLE_RADIUS,
    backgroundColor: HERO_BACKGROUND,
    zIndex: 0,
  },
  mascot: {
    width: MASCOT_WIDTH,
    height: MASCOT_HEIGHT,
    zIndex: 1,
  },
  formArea: {
    paddingHorizontal: 20,
    paddingTop: 20,
    paddingBottom: 24,
  },
  heading: {
    fontSize: 16,
    lineHeight: 22,
    fontWeight: '700',
    color: colors.text,
    textAlign: 'center',
    marginBottom: 16,
  },
  headingHighlight: {
    color: colors.primary,
  },
  title: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.text,
    marginBottom: 10,
  },
  linkRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 16,
  },
  link: {
    fontSize: 12,
    color: colors.text,
    textDecorationLine: 'underline',
  },
  dividerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 16,
    marginBottom: 16,
  },
  dividerLine: {
    flex: 1,
    height: 1,
    backgroundColor: colors.border,
  },
  dividerText: {
    fontSize: 12,
    color: colors.textSecondary,
    marginHorizontal: 8,
  },
  kakaoRow: {
    alignItems: 'center',
  },
});

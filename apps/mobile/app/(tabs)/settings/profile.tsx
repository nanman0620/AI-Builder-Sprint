import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { ErrorView } from '@/src/components/common/error-view';
import { colors, spacing, typography } from '@/src/constants/tokens';
import { AuthSubmitButton } from '@/src/features/auth/components/auth-submit-button';
import { AuthTextInput } from '@/src/features/auth/components/auth-text-input';
import { getProfile, updateProfileNickname } from '@/src/features/settings/api';
import type { Profile } from '@/src/features/settings/types';
import { validateNickname, validatePassword } from '@/src/features/settings/validation';

export default function SettingsProfileScreen() {
  const router = useRouter();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [nickname, setNickname] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadProfile() {
      setErrorMessage(null);
      setSuccessMessage(null);
      setIsLoading(true);
      try {
        const response = await getProfile();
        if (cancelled) {
          return;
        }
        setProfile(response);
        setNickname(response.nickname);
        setEmail(response.email);
      } catch {
        if (!cancelled) {
          setErrorMessage('정보를 불러오지 못했습니다.');
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    loadProfile();

    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSave() {
    if (isSaving) {
      return;
    }

    setErrorMessage(null);
    setSuccessMessage(null);

    const nicknameError = validateNickname(nickname);
    if (nicknameError) {
      setErrorMessage(nicknameError);
      return;
    }

    const passwordError = validatePassword(password, passwordConfirm);
    if (passwordError) {
      setErrorMessage(passwordError);
      return;
    }

    const trimmedNickname = nickname.trim();
    const hasNicknameChange = profile ? trimmedNickname !== profile.nickname : false;
    const hasPasswordInput = password.length > 0 || passwordConfirm.length > 0;

    if (!hasNicknameChange && !hasPasswordInput) {
      setSuccessMessage('변경사항이 없습니다.');
      return;
    }

    setIsSaving(true);
    try {
      let updatedProfile = profile;

      if (hasNicknameChange && profile) {
        updatedProfile = await updateProfileNickname(trimmedNickname);
        setProfile(updatedProfile);
        setNickname(updatedProfile.nickname);
      }

      if (password && passwordConfirm && password === passwordConfirm) {
        setPassword('');
        setPasswordConfirm('');
      }

      setSuccessMessage('변경사항이 저장되었습니다.');
    } catch {
      setErrorMessage('변경사항을 저장하지 못했습니다.');
    } finally {
      setIsSaving(false);
    }
  }

  if (isLoading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  if (!profile) {
    return <ErrorView onRetry={() => router.replace('/(tabs)/settings')} />;
  }

  return (
    <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} style={styles.backButton}>
          <Text style={styles.backText}>뒤로</Text>
        </Pressable>
        <Text style={styles.title}>개인정보 수정</Text>
      </View>
      <View style={styles.fieldContainer}>
        <Text style={styles.label}>이메일</Text>
        <View style={styles.readOnlyBox}>
          <Text style={styles.readOnlyText}>{email}</Text>
        </View>
      </View>
      <AuthTextInput
        label="닉네임"
        value={nickname}
        onChangeText={setNickname}
        placeholder="닉네임을 입력해 주세요"
      />
      <AuthTextInput
        label="새 비밀번호"
        secureTextEntry
        secureToggle
        value={password}
        onChangeText={setPassword}
        placeholder="새 비밀번호"
      />
      <AuthTextInput
        label="새 비밀번호 확인"
        secureTextEntry
        secureToggle
        value={passwordConfirm}
        onChangeText={setPasswordConfirm}
        placeholder="새 비밀번호 확인"
      />
      {errorMessage ? <Text style={styles.errorText}>{errorMessage}</Text> : null}
      {successMessage ? <Text style={styles.successText}>{successMessage}</Text> : null}
      <AuthSubmitButton label="저장" onPress={handleSave} loading={isSaving} disabled={isSaving} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flexGrow: 1,
    backgroundColor: colors.background,
    padding: spacing.lg,
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.background,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.lg,
  },
  backButton: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
  },
  backText: {
    ...typography.body,
    color: colors.primary,
  },
  title: {
    ...typography.title,
    color: colors.text,
    flex: 1,
    textAlign: 'center',
    marginRight: spacing.md,
  },
  fieldContainer: {
    marginBottom: spacing.md,
  },
  label: {
    ...typography.body,
    color: colors.textSecondary,
    marginBottom: spacing.xs,
  },
  readOnlyBox: {
    backgroundColor: colors.primarySoft,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
  },
  readOnlyText: {
    ...typography.body,
    color: colors.textSecondary,
  },
  errorText: {
    color: colors.error,
    marginBottom: spacing.md,
  },
  successText: {
    color: colors.primary,
    marginBottom: spacing.md,
  },
});

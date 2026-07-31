import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { colors, spacing, typography } from '@/src/constants/tokens';
import { AuthSubmitButton } from '@/src/features/auth/components/auth-submit-button';
import { signOut } from '@/src/features/auth/services/auth-service';

export default function AccountWithdrawalScreen() {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleCancel() {
    router.back();
  }

  async function handleWithdraw() {
    if (isSubmitting) {
      return;
    }

    setIsSubmitting(true);
    try {
      await signOut();
      Alert.alert('회원탈퇴 완료', '회원탈퇴가 완료되었습니다.', [
        {
          text: '확인',
          onPress: () => router.replace('/(auth)/login'),
        },
      ]);
    } catch {
      Alert.alert('오류', '회원탈퇴 처리 중 문제가 발생했습니다. 다시 시도해 주세요.');
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
      <View style={styles.card}>
        <Text style={styles.title}>정말 회원탈퇴하시겠어요?</Text>
        <Text style={styles.description}>
          회원탈퇴를 진행하면
          {'\n'}현재 계정에서 로그아웃됩니다.
        </Text>
        <Text style={styles.note}>
          해커톤 MVP에서는 실제 계정과
          {'\n'}서버 데이터는 삭제되지 않습니다.
        </Text>
        <View style={styles.buttonColumn}>
          <Pressable style={[styles.cancelButton, styles.cancelMargin]} onPress={handleCancel} disabled={isSubmitting}>
            <Text style={styles.cancelText}>취소</Text>
          </Pressable>
          <AuthSubmitButton label="회원탈퇴" onPress={handleWithdraw} loading={isSubmitting} />
        </View>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flexGrow: 1,
    backgroundColor: colors.background,
    padding: spacing.lg,
    justifyContent: 'center',
  },
  card: {
    backgroundColor: colors.background,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
  },
  title: {
    ...typography.title,
    color: colors.text,
    marginBottom: spacing.sm,
  },
  description: {
    ...typography.body,
    color: colors.textSecondary,
    lineHeight: 22,
    marginBottom: spacing.md,
  },
  note: {
    ...typography.caption,
    color: colors.textSecondary,
    lineHeight: 20,
    marginBottom: spacing.lg,
  },
  buttonColumn: {
    flexDirection: 'column',
    justifyContent: 'center',
  },
  cancelMargin: {
    marginBottom: spacing.sm,
  },
  cancelButton: {
    height: 46,
    borderRadius: 12,
    backgroundColor: colors.border,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  cancelText: {
    ...typography.body,
    fontWeight: '700',
    color: colors.text,
  },
});

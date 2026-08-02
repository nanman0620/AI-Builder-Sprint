import AsyncStorage from '@react-native-async-storage/async-storage';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Image, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Svg, { Path } from 'react-native-svg';

import { colors, fonts } from '@/src/constants/tokens';
import { useAppSync } from '@/src/features/app-sync/app-sync-context';
import { performAccountWithdrawal } from '@/src/features/auth/account-withdrawal-flow';
import { signOut } from '@/src/features/auth/services/auth-service';
import { forceClearLocalSession, isLocalSessionCleared } from '@/src/features/auth/services/local-session';
import { useBootstrap } from '@/src/features/bootstrap/bootstrap-context';
import { apiRequest } from '@/src/services/api/client';
import { showAlert } from '@/src/utils/alert';

const mascotSad = require('@/assets/brand/mascot-sad.png');

const TEXT = '#1D1D23';
const PURPLE = '#D791FF';
const BUTTON_BORDER = '#E6E1E9';

function ChevronLeftIcon({ size = 14, color = TEXT }: { size?: number; color?: string }) {
  const width = (size * 7.44075) / 13.8577;
  return (
    <Svg width={width} height={size} viewBox="0 0 7.44075 13.8577">
      <Path
        d="M1.56769 6.93183L7.21725 12.5814C7.36625 12.7304 7.43888 12.9058 7.43513 13.1077C7.43125 13.3097 7.35481 13.4852 7.20581 13.6342C7.05669 13.7832 6.88119 13.8577 6.67931 13.8577C6.47744 13.8577 6.30194 13.7832 6.15281 13.6342L0.399563 7.8924C0.263938 7.75677 0.163438 7.60483 0.0980627 7.43658C0.0326877 7.26833 0 7.10008 0 6.93183C0 6.76358 0.0326877 6.59533 0.0980627 6.42708C0.163438 6.25883 0.263938 6.1069 0.399563 5.97127L6.15281 0.217835C6.30194 0.0688345 6.47938 -0.00372767 6.68513 0.000147333C6.89088 0.00402233 7.06825 0.0804595 7.21725 0.229459C7.36625 0.378459 7.44075 0.55396 7.44075 0.75596C7.44075 0.957835 7.36625 1.13327 7.21725 1.28227L1.56769 6.93183Z"
        fill={color}
      />
    </Svg>
  );
}

export default function AccountWithdrawalScreen() {
  const router = useRouter();
  const { reset: resetAppSync } = useAppSync();
  const { reset: resetBootstrap } = useBootstrap();
  const [isSubmitting, setIsSubmitting] = useState(false);

  function handleBack() {
    router.back();
  }

  async function handleWithdraw() {
    if (isSubmitting) {
      return;
    }

    setIsSubmitting(true);
    try {
      await performAccountWithdrawal({
        deleteAccount: () => apiRequest('/me', { method: 'DELETE' }),
        signOutLocal: () => signOut({ scope: 'local' }),
        forceClearLocalSession,
        isLocalSessionCleared,
        clearAllLocalData: () => AsyncStorage.clear(),
        resetAppSync,
        resetBootstrap,
        onSuccess: () => {
          showAlert('회원탈퇴 완료', '회원탈퇴가 완료되었습니다.', [
            {
              text: '확인',
              onPress: () => router.replace('/(auth)/login'),
            },
          ]);
        },
        onAuthDeletionFailed: () => {
          showAlert('알림', '탈퇴 데이터는 삭제됐지만 계정 삭제가 완료되지 않았어요. 다시 시도해 주세요.');
        },
        onGenericError: () => {
          showAlert('오류', '회원탈퇴 처리 중 문제가 발생했습니다. 다시 시도해 주세요.');
        },
        onLocalSessionCleanupFailed: () => {
          showAlert(
            '알림',
            '계정 삭제는 완료됐지만 기기에서 로그인 정보를 완전히 지우지 못했어요. 앱을 다시 시작해 주세요.'
          );
        },
      });
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <SafeAreaView style={styles.safeArea} edges={['top']}>
      <View style={styles.header}>
        <Pressable onPress={handleBack} style={styles.backButton} hitSlop={8} disabled={isSubmitting}>
          <ChevronLeftIcon size={14} color={TEXT} />
        </Pressable>
        <Text style={styles.headerTitle}>회원 탈퇴</Text>
      </View>

      <View style={styles.body}>
        <Text style={styles.title}>
          탈퇴하신다니 정말 아쉬워요{'\n'}정말 탈퇴하시겠어요?
        </Text>
        <Image source={mascotSad} style={styles.mascot} resizeMode="contain" />
        <View style={styles.buttonRow}>
          <Pressable
            style={[styles.yesButton, isSubmitting ? styles.buttonDisabled : null]}
            onPress={handleWithdraw}
            disabled={isSubmitting}>
            <Text style={styles.yesButtonText}>네</Text>
          </Pressable>
          <Pressable style={styles.noButton} onPress={handleBack} disabled={isSubmitting}>
            <Text style={styles.noButtonText}>아니요</Text>
          </Pressable>
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingVertical: 14,
    borderBottomWidth: 0.72,
    borderBottomColor: BUTTON_BORDER,
  },
  backButton: {
    position: 'absolute',
    left: 20,
    zIndex: 1,
    padding: 4,
  },
  headerTitle: {
    flex: 1,
    fontSize: 15,
    fontFamily: fonts.bold,
    color: TEXT,
    textAlign: 'center',
  },
  body: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 35,
  },
  title: {
    fontSize: 20,
    fontFamily: fonts.bold,
    color: TEXT,
    textAlign: 'center',
  },
  mascot: {
    width: 160,
    height: 160,
    marginTop: 32,
  },
  buttonRow: {
    flexDirection: 'row',
    gap: 16,
    width: '100%',
    marginTop: 48,
  },
  yesButton: {
    flex: 1,
    height: 44,
    borderRadius: 8,
    backgroundColor: '#FFFFFF',
    borderWidth: 1,
    borderColor: BUTTON_BORDER,
    alignItems: 'center',
    justifyContent: 'center',
  },
  yesButtonText: {
    fontSize: 16,
    fontFamily: fonts.bold,
    color: TEXT,
  },
  noButton: {
    flex: 1,
    height: 44,
    borderRadius: 8,
    backgroundColor: PURPLE,
    alignItems: 'center',
    justifyContent: 'center',
  },
  noButtonText: {
    fontSize: 16,
    fontFamily: fonts.bold,
    color: '#FFFFFF',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
});

import { useFocusEffect } from '@react-navigation/native';
import { useRouter } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { ErrorView } from '@/src/components/common/error-view';
import { colors, spacing, typography } from '@/src/constants/tokens';
import { signOut } from '@/src/features/auth/services/auth-service';
import { getProfile } from '@/src/features/settings/api';
import { LogoutConfirmModal } from '@/src/features/settings/components/LogoutConfirmModal';
import { ProfileCard } from '@/src/features/settings/components/ProfileCard';
import type { Profile } from '@/src/features/settings/types';

export default function SettingsScreen() {
  const router = useRouter();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const [isLogoutVisible, setIsLogoutVisible] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const profileRef = useRef<Profile | null>(null);
  const isMountedRef = useRef(true);
  const inFlightRef = useRef<Promise<void> | null>(null);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const loadProfile = useCallback((): Promise<void> => {
    if (inFlightRef.current) {
      return inFlightRef.current;
    }

    if (isMountedRef.current) {
      setLoadError(null);
      setLogoutError(null);
      if (!profileRef.current) {
        setIsLoading(true);
      }
    }

    const request = getProfile()
      .then((response) => {
        profileRef.current = response;
        if (isMountedRef.current) {
          setProfile(response);
        }
      })
      .catch(() => {
        if (isMountedRef.current) {
          setLoadError(
            profileRef.current ? '프로필을 새로 불러오지 못했습니다.' : '정보를 불러오지 못했어요.'
          );
        }
      })
      .finally(() => {
        inFlightRef.current = null;
        if (isMountedRef.current) {
          setIsLoading(false);
        }
      });

    inFlightRef.current = request;
    return request;
  }, []);

  useFocusEffect(
    useCallback(() => {
      void loadProfile();
    }, [loadProfile])
  );

  async function handleLogout() {
    if (isSubmitting) {
      return;
    }
    setIsSubmitting(true);
    setLogoutError(null);
    try {
      await signOut();
      router.replace('/(auth)/login');
    } catch {
      setLogoutError('로그아웃에 실패했습니다. 다시 시도해 주세요.');
    } finally {
      setIsSubmitting(false);
    }
  }

  if (loadError && !profile) {
    return <ErrorView onRetry={loadProfile} />;
  }

  return (
    <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
      <Text style={styles.title}>설정</Text>
      {isLoading || !profile ? (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={colors.primary} />
        </View>
      ) : (
        <>
          <ProfileCard profile={profile} />
          <View style={styles.group}>
            <Text style={styles.groupTitle}>계정 관리</Text>
            <Pressable style={styles.menuItem} onPress={() => router.push('/(tabs)/settings/profile')}>
              <Text style={styles.menuText}>개인정보 수정</Text>
            </Pressable>
            <Pressable style={styles.menuItem} onPress={() => setIsLogoutVisible(true)}>
              <Text style={styles.menuText}>로그아웃</Text>
            </Pressable>
            <Pressable style={styles.menuItem} onPress={() => router.push('/account-withdrawal')}>
              <Text style={styles.menuText}>회원탈퇴</Text>
            </Pressable>
            {logoutError ? <Text style={styles.errorText}>{logoutError}</Text> : null}
            {loadError && profile ? <Text style={styles.errorText}>{loadError}</Text> : null}
          </View>
        </>
      )}
      <LogoutConfirmModal
        visible={isLogoutVisible}
        loading={isSubmitting}
        onCancel={() => setIsLogoutVisible(false)}
        onConfirm={handleLogout}
      />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flexGrow: 1,
    backgroundColor: colors.background,
    padding: spacing.lg,
  },
  title: {
    ...typography.title,
    color: colors.text,
    marginBottom: spacing.lg,
  },
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 240,
  },
  group: {
    marginTop: spacing.md,
  },
  groupTitle: {
    ...typography.body,
    color: colors.textSecondary,
    marginBottom: spacing.sm,
  },
  menuItem: {
    backgroundColor: colors.background,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    marginBottom: spacing.sm,
  },
  menuText: {
    ...typography.body,
    color: colors.text,
  },
  errorText: {
    ...typography.body,
    color: colors.error,
    marginTop: spacing.sm,
  },
});

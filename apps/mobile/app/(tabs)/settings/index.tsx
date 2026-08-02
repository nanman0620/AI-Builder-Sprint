import { useFocusEffect } from '@react-navigation/native';
import { useRouter } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Image, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { ErrorView } from '@/src/components/common/error-view';
import { colors, fonts } from '@/src/constants/tokens';
import { useAppSync } from '@/src/features/app-sync/app-sync-context';
import { signOut } from '@/src/features/auth/services/auth-service';
import { useBootstrap } from '@/src/features/bootstrap/bootstrap-context';
import { getProfile } from '@/src/features/settings/api';
import { LogoutConfirmModal } from '@/src/features/settings/components/LogoutConfirmModal';
import { ProfileCard } from '@/src/features/settings/components/ProfileCard';
import type { Profile } from '@/src/features/settings/types';

export default function SettingsScreen() {
  const router = useRouter();
  const { epochs, reset: resetAppSync, resetEpoch } = useAppSync();
  const { reset: resetBootstrap } = useBootstrap();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const [isLogoutVisible, setIsLogoutVisible] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const profileRef = useRef<Profile | null>(null);
  const isMountedRef = useRef(true);
  const inFlightRef = useRef<Promise<void> | null>(null);
  const loadGenerationRef = useRef(0);
  const isFocusedRef = useRef(false);
  const seenRefreshEpochRef = useRef(epochs.profile);
  const seenResetEpochRef = useRef(resetEpoch);

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

    const generation = loadGenerationRef.current;
    const request = getProfile()
      .then((response) => {
        if (generation !== loadGenerationRef.current) {
          return;
        }
        profileRef.current = response;
        if (isMountedRef.current && generation === loadGenerationRef.current) {
          setProfile(response);
        }
      })
      .catch(() => {
        if (isMountedRef.current && generation === loadGenerationRef.current) {
          setLoadError('정보를 불러오지 못했어요.\n잠시 후 다시 시도해 주세요.');
        }
      })
      .finally(() => {
        if (inFlightRef.current === request) {
          inFlightRef.current = null;
        }
        if (isMountedRef.current && generation === loadGenerationRef.current) {
          setIsLoading(false);
        }
      });

    inFlightRef.current = request;
    return request;
  }, []);

  useFocusEffect(
    useCallback(() => {
      isFocusedRef.current = true;
      void loadProfile();
      return () => {
        isFocusedRef.current = false;
      };
    }, [loadProfile])
  );

  useEffect(() => {
    if (seenRefreshEpochRef.current === epochs.profile) {
      return;
    }
    seenRefreshEpochRef.current = epochs.profile;
    if (isFocusedRef.current) {
      void loadProfile();
    }
  }, [epochs.profile, loadProfile]);

  useEffect(() => {
    if (seenResetEpochRef.current === resetEpoch) {
      return;
    }
    seenResetEpochRef.current = resetEpoch;
    isFocusedRef.current = false;
    loadGenerationRef.current += 1;
    inFlightRef.current = null;
    profileRef.current = null;
    setProfile(null);
    setIsLoading(true);
    setLoadError(null);
    setLogoutError(null);
  }, [resetEpoch]);

  async function handleLogout() {
    if (isSubmitting) {
      return;
    }
    setIsSubmitting(true);
    setLogoutError(null);
    try {
      resetAppSync();
      resetBootstrap();
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
    <View style={styles.safeArea}>
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <View style={styles.header}>
          <Text style={styles.headerTitle}>설정</Text>
        </View>
        {isLoading || !profile ? (
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color={PURPLE} />
          </View>
        ) : (
          <>
            <View style={styles.content}>
              <ProfileCard profile={profile} />
              <View style={styles.menuGroup}>
                <Pressable style={styles.menuCard} onPress={() => router.push('/(tabs)/settings/profile')}>
                  <Text style={styles.menuTitle}>개인정보 수정</Text>
                  <Text style={styles.menuSubtitle}>닉네임·이메일·비밀번호를 수정해요</Text>
                </Pressable>
                <Pressable style={styles.menuCard} onPress={() => setIsLogoutVisible(true)}>
                  <Text style={styles.menuTitle}>로그아웃</Text>
                  <Text style={styles.menuSubtitle}>현재 기기에서 로그아웃</Text>
                </Pressable>
                <Pressable style={styles.menuCard} onPress={() => router.push('/account-withdrawal')}>
                  <Text style={styles.menuTitle}>회원탈퇴</Text>
                  <Text style={styles.menuSubtitle}>이음 서비스 탈퇴</Text>
                </Pressable>
                {logoutError ? <Text style={styles.errorText}>{logoutError}</Text> : null}
                {loadError && profile ? (
                  <View style={styles.refreshError}>
                    <Text style={styles.errorText}>{loadError}</Text>
                    <Pressable disabled={isLoading} onPress={() => void loadProfile()}>
                      <Text style={styles.retryText}>다시 시도</Text>
                    </Pressable>
                  </View>
                ) : null}
              </View>
            </View>
            <View style={styles.footer}>
              <Image
                source={require('@/assets/brand/eum-logo-tagline.png')}
                style={styles.footerLogo}
                resizeMode="contain"
              />
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
    </View>
  );
}

const PURPLE = '#D791FF';
const TEXT = '#1D1D23';
const TEXT_SECONDARY = '#85818A';
const BORDER = '#E6E1E9';

const LOGO_TAGLINE_RATIO = 232 / 403;
const LOGO_WIDTH = 140;

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: colors.background,
  },
  container: {
    flexGrow: 1,
    backgroundColor: colors.background,
  },
  header: {
    paddingVertical: 14,
    borderBottomWidth: 0.72,
    borderBottomColor: BORDER,
  },
  headerTitle: {
    fontSize: 15,
    fontFamily: fonts.bold,
    color: TEXT,
    textAlign: 'center',
  },
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 240,
  },
  content: {
    marginTop: 21,
  },
  menuGroup: {
    marginTop: 9,
  },
  menuCard: {
    height: 77,
    justifyContent: 'center',
    backgroundColor: colors.background,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: BORDER,
    paddingLeft: 18,
    marginHorizontal: 21,
    marginBottom: 12,
  },
  menuTitle: {
    fontSize: 14,
    fontFamily: fonts.semiBold,
    color: TEXT,
  },
  menuSubtitle: {
    marginTop: 4,
    fontSize: 10,
    fontFamily: fonts.regular,
    color: TEXT_SECONDARY,
  },
  errorText: {
    fontSize: 13,
    fontFamily: fonts.regular,
    color: colors.error,
    marginTop: 8,
    marginHorizontal: 21,
  },
  refreshError: {
    marginTop: 8,
  },
  retryText: {
    fontSize: 13,
    color: PURPLE,
    fontFamily: fonts.bold,
    marginTop: 8,
    marginHorizontal: 21,
  },
  footer: {
    marginTop: 130,
    marginBottom: 32,
    alignItems: 'center',
  },
  footerLogo: {
    width: LOGO_WIDTH,
    height: LOGO_WIDTH * LOGO_TAGLINE_RATIO,
  },
});

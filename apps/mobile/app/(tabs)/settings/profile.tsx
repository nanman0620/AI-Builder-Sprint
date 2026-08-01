import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Svg, { Path } from 'react-native-svg';

import { ErrorView } from '@/src/components/common/error-view';
import { colors, fonts } from '@/src/constants/tokens';
import { getProfile, updateProfileNickname } from '@/src/features/settings/api';
import type { Profile } from '@/src/features/settings/types';
import { validateNickname, validatePassword } from '@/src/features/settings/validation';

const PURPLE = '#D791FF';
const TEXT = '#1D1D23';
const TEXT_SECONDARY = '#85818A';
const INPUT_BORDER = '#E6E1E9';

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

function EyeIcon({ size = 20, color = TEXT_SECONDARY }: { size?: number; color?: string }) {
  const height = (size * 15.1667) / 20.66;
  return (
    <Svg width={size} height={height} viewBox="0 0 20.66 15.1667">
      <Path
        d="M12.5608 9.81417C13.1719 9.20306 13.4775 8.45944 13.4775 7.58333C13.4775 6.70722 13.1719 5.96361 12.5608 5.3525C11.9497 4.74139 11.2061 4.43583 10.33 4.43583C9.45389 4.43583 8.71028 4.74139 8.09917 5.3525C7.48806 5.96361 7.1825 6.70722 7.1825 7.58333C7.1825 8.45944 7.48806 9.20306 8.09917 9.81417C8.71028 10.4253 9.45389 10.7308 10.33 10.7308C11.2061 10.7308 11.9497 10.4253 12.5608 9.81417ZM8.91333 9C8.52444 8.61111 8.33 8.13889 8.33 7.58333C8.33 7.02778 8.52444 6.55556 8.91333 6.16667C9.30222 5.77778 9.77444 5.58333 10.33 5.58333C10.8856 5.58333 11.3578 5.77778 11.7467 6.16667C12.1356 6.55556 12.33 7.02778 12.33 7.58333C12.33 8.13889 12.1356 8.61111 11.7467 9C11.3578 9.38889 10.8856 9.58333 10.33 9.58333C9.77444 9.58333 9.30222 9.38889 8.91333 9ZM5.63125 11.8148C4.1975 10.9137 3.04687 9.72757 2.17937 8.25646C2.10993 8.15062 2.06264 8.04056 2.0375 7.92625C2.0125 7.81194 2 7.69764 2 7.58333C2 7.46903 2.0125 7.35472 2.0375 7.24042C2.06264 7.12611 2.10993 7.01604 2.17937 6.91021C3.04687 5.4391 4.1975 4.25299 5.63125 3.35188C7.065 2.45063 8.63125 2 10.33 2C12.0287 2 13.595 2.45063 15.0288 3.35188C16.4625 4.25299 17.6131 5.4391 18.4806 6.91021C18.5501 7.01604 18.5974 7.12611 18.6225 7.24042C18.6475 7.35472 18.66 7.46903 18.66 7.58333C18.66 7.69764 18.6475 7.81194 18.6225 7.92625C18.5974 8.04056 18.5501 8.15062 18.4806 8.25646C17.6131 9.72757 16.4625 10.9137 15.0288 11.8148C13.595 12.716 12.0287 13.1667 10.33 13.1667C8.63125 13.1667 7.065 12.716 5.63125 11.8148ZM14.6425 10.875C15.9619 10.0694 16.9758 8.97222 17.6842 7.58333C16.9758 6.19444 15.9619 5.09722 14.6425 4.29167C13.3231 3.48611 11.8856 3.08333 10.33 3.08333C8.77444 3.08333 7.33694 3.48611 6.0175 4.29167C4.69806 5.09722 3.68417 6.19444 2.97583 7.58333C3.68417 8.97222 4.69806 10.0694 6.0175 10.875C7.33694 11.6806 8.77444 12.0833 10.33 12.0833C11.8856 12.0833 13.3231 11.6806 14.6425 10.875Z"
        fill={color}
      />
    </Svg>
  );
}

type LabeledInputProps = {
  label: string;
  value: string;
  onChangeText?: (value: string) => void;
  placeholder: string;
  editable?: boolean;
  secureToggle?: boolean;
};

function LabeledInput({ label, value, onChangeText, placeholder, editable = true, secureToggle = false }: LabeledInputProps) {
  const [isVisible, setIsVisible] = useState(false);

  return (
    <View style={styles.fieldContainer}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <View style={styles.inputBox}>
        <TextInput
          style={styles.inputText}
          value={value}
          onChangeText={onChangeText}
          placeholder={placeholder}
          placeholderTextColor={TEXT_SECONDARY}
          editable={editable}
          secureTextEntry={secureToggle && !isVisible}
          autoCapitalize="none"
        />
        {secureToggle ? (
          <Pressable onPress={() => setIsVisible((prev) => !prev)} hitSlop={8}>
            <EyeIcon size={20} color={TEXT_SECONDARY} />
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

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
      <SafeAreaView style={styles.centered} edges={['top']}>
        <ActivityIndicator size="large" color={PURPLE} />
      </SafeAreaView>
    );
  }

  if (!profile) {
    return <ErrorView onRetry={() => router.replace('/(tabs)/settings')} />;
  }

  return (
    <SafeAreaView style={styles.safeArea} edges={['top']}>
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} style={styles.backButton} hitSlop={8}>
            <ChevronLeftIcon size={14} color={TEXT} />
          </Pressable>
          <Text style={styles.headerTitle}>개인 정보 수정</Text>
        </View>

        <View style={styles.formArea}>
          <LabeledInput
            label="닉네임"
            value={nickname}
            onChangeText={setNickname}
            placeholder="닉네임을 입력하세요"
          />
          <LabeledInput label="이메일" value={email} placeholder="이메일을 입력하세요" editable={false} />
          <LabeledInput
            label="새 비밀번호"
            value={password}
            onChangeText={setPassword}
            placeholder="8자 이상의 비밀번호를 입력하세요"
            secureToggle
          />
          <LabeledInput
            label="새 비밀번호 확인"
            value={passwordConfirm}
            onChangeText={setPasswordConfirm}
            placeholder="비밀번호를 한 번 더 입력하세요"
            secureToggle
          />

          {errorMessage ? <Text style={styles.errorText}>{errorMessage}</Text> : null}
          {successMessage ? <Text style={styles.successText}>{successMessage}</Text> : null}

          <Pressable
            style={[styles.saveButton, isSaving ? styles.saveButtonDisabled : null]}
            onPress={handleSave}
            disabled={isSaving}>
            {isSaving ? <ActivityIndicator color="#FFFFFF" /> : <Text style={styles.saveButtonText}>저장</Text>}
          </Pressable>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: colors.background,
  },
  container: {
    flexGrow: 1,
    backgroundColor: colors.background,
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.background,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingVertical: 14,
    borderBottomWidth: 0.72,
    borderBottomColor: INPUT_BORDER,
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
  formArea: {
    marginTop: 32,
    marginHorizontal: 30,
  },
  fieldContainer: {
    marginBottom: 16,
  },
  fieldLabel: {
    fontSize: 14,
    fontFamily: fonts.bold,
    color: TEXT,
    marginBottom: 8,
  },
  inputBox: {
    flexDirection: 'row',
    alignItems: 'center',
    height: 47,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: INPUT_BORDER,
    paddingHorizontal: 20,
  },
  inputText: {
    flex: 1,
    fontSize: 14,
    fontFamily: fonts.medium,
    color: TEXT,
    padding: 0,
  },
  errorText: {
    fontSize: 13,
    fontFamily: fonts.regular,
    color: colors.error,
    marginBottom: 12,
  },
  successText: {
    fontSize: 13,
    fontFamily: fonts.regular,
    color: PURPLE,
    marginBottom: 12,
  },
  saveButton: {
    height: 47,
    borderRadius: 8,
    backgroundColor: PURPLE,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 24,
  },
  saveButtonDisabled: {
    opacity: 0.6,
  },
  saveButtonText: {
    fontSize: 16,
    fontFamily: fonts.semiBold,
    color: '#FFFFFF',
  },
});

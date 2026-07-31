import { StyleSheet, Text, View } from 'react-native';

import { colors, spacing, typography } from '@/src/constants/tokens';
import type { Profile } from '../types';

type ProfileCardProps = {
  profile: Profile;
};

export function ProfileCard({ profile }: ProfileCardProps) {
  return (
    <View style={styles.card}>
      <Text style={styles.title}>프로필</Text>
      <View style={styles.row}>
        <Text style={styles.label}>닉네임</Text>
        <Text style={styles.value}>{profile.nickname}</Text>
      </View>
      <View style={styles.row}>
        <Text style={styles.label}>이메일</Text>
        <Text style={styles.value}>{profile.email}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.background,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    marginBottom: spacing.lg,
  },
  title: {
    ...typography.title,
    color: colors.text,
    marginBottom: spacing.md,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.sm,
  },
  label: {
    ...typography.body,
    color: colors.textSecondary,
  },
  value: {
    ...typography.body,
    color: colors.text,
    fontWeight: '700',
  },
});

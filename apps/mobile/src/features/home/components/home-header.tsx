import { StyleSheet, Text, View } from 'react-native';

import { colors, spacing, typography } from '@/src/constants/tokens';

import { formatLogicalDateBadge } from '../logic';

type HomeHeaderProps = {
  logicalDate: string;
  badgeLabel?: string;
  nickname?: string | null;
  title: string;
  description?: string;
};

// UI-005~UI-009 공통 상단 영역: 날짜 배지(+선택적 경고 배지) → 제목 → 선택적 설명.
// FINALIZING(UI-010)은 이 헤더를 쓰지 않는 완전히 다른 전체화면 레이아웃이라 별도 컴포넌트(FinalizingView)로 둔다.
export function HomeHeader({ logicalDate, badgeLabel, nickname, title, description }: HomeHeaderProps) {
  const trimmedNickname = nickname?.trim();
  const greeting = nickname !== undefined ? (trimmedNickname ? `${trimmedNickname}님,` : '안녕하세요,') : null;

  return (
    <View style={styles.container}>
      <View style={styles.badgeRow}>
        <View style={styles.dateBadge}>
          <Text style={styles.dateBadgeText}>{formatLogicalDateBadge(logicalDate)}</Text>
        </View>
        {badgeLabel ? (
          <View style={styles.warningBadge}>
            <Text style={styles.warningBadgeText}>{badgeLabel}</Text>
          </View>
        ) : null}
      </View>
      <Text style={styles.title}>
        {greeting ? `${greeting}\n` : ''}
        {title}
      </Text>
      {description ? <Text style={styles.description}>{description}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg + 4,
  },
  badgeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  dateBadge: {
    backgroundColor: colors.text,
    borderRadius: 999,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    marginRight: spacing.xs,
  },
  dateBadgeText: {
    ...typography.caption,
    color: colors.background,
    fontWeight: '700',
  },
  warningBadge: {
    borderColor: colors.warning,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
  },
  warningBadgeText: {
    ...typography.caption,
    color: colors.warning,
    fontWeight: '700',
  },
  title: {
    ...typography.title,
    color: colors.text,
    fontSize: 17,
    marginLeft: 8,
  },
  description: {
    ...typography.body,
    color: colors.textSecondary,
    marginTop: spacing.xs,
  },
});

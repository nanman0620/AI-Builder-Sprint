import { StyleSheet, Text, View } from 'react-native';

import { colors, fonts, spacing, typography } from '@/src/constants/tokens';

import type { RequestItemSnapshot, SolarRequestItem } from '../types';
import { getRequestItemCardDisplay } from './request-item-card-display';

// 캡처(UI-014/UI-015)의 고정 일정 배지 색은 공용 디자인 토큰에 없어 이 컴포넌트에서만 쓴다.
const FIXED_SCHEDULE_BADGE_BACKGROUND = '#DBEAFE';
const FIXED_SCHEDULE_BADGE_TEXT = '#2563EB';

type RequestItemCardProps = {
  item: SolarRequestItem | RequestItemSnapshot;
  highlighted?: boolean;
};

// 제목·상태 문구·배지 문구는 서버가 내려주는 title/summaryText/statusLabel/entityLabel을
// 그대로 표시한다. deadlineAt/amountText/estimatedMinutes 등으로 프론트에서 다시 조합하지 않는다.
export function RequestItemCard({ item, highlighted = false }: RequestItemCardProps) {
  const isInfoMissing = item.status === 'INFO_MISSING';
  const isFixedSchedule = item.entityType === 'FIXED_SCHEDULE';
  const display = getRequestItemCardDisplay(item);

  return (
    <View style={[styles.card, highlighted && styles.cardHighlighted]}>
      <View style={styles.header}>
        <Text style={styles.title} numberOfLines={1}>
          {item.title}
        </Text>
        <View
          style={[
            styles.badge,
            {
              backgroundColor: display.isDelete
                ? `${colors.error}1A`
                : isFixedSchedule
                  ? FIXED_SCHEDULE_BADGE_BACKGROUND
                  : colors.primarySoft,
            },
          ]}>
          <Text
            style={[
              styles.badgeText,
              {
                color: display.isDelete
                  ? colors.error
                  : isFixedSchedule
                    ? FIXED_SCHEDULE_BADGE_TEXT
                    : colors.primary,
              },
            ]}>
            {display.badgeLabel}
          </Text>
        </View>
      </View>
      <Text style={[styles.statusLine, (isInfoMissing || display.isDelete) && styles.statusLineError]}>
        {display.summaryText}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 16,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  cardHighlighted: {
    borderColor: colors.primary,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  title: {
    ...typography.body,
    fontFamily: fonts.bold,
    color: colors.text,
    flex: 1,
    marginRight: spacing.sm,
  },
  badge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    borderRadius: 999,
  },
  badgeText: {
    ...typography.caption,
    fontFamily: fonts.semiBold,
  },
  statusLine: {
    ...typography.caption,
    color: colors.textSecondary,
    marginTop: spacing.xs,
  },
  statusLineError: {
    color: colors.error,
  },
});

import { useState } from 'react';
import { Image, Pressable, StyleSheet, Text, View, type StyleProp, type TextStyle } from 'react-native';

import { colors, fonts, spacing, typography } from '@/src/constants/tokens';

import { formatLogicalDateBadge } from '../logic';
import { ShopComingSoonModal } from './shop-coming-soon-modal';

const SHOP_ICON_SOURCE = require('@/assets/brand/shop-entry-icon.png');

type HomeHeaderProps = {
  logicalDate: string;
  badgeLabel?: string;
  nickname?: string | null;
  title: string;
  feedback?: string;
  description?: string;
  showShopIcon?: boolean;
  titleStyle?: StyleProp<TextStyle>;
  descriptionStyle?: StyleProp<TextStyle>;
  descriptionNumberOfLines?: number;
};

type HomeDateBadgeProps = {
  logicalDate: string;
};

export function HomeDateBadge({ logicalDate }: HomeDateBadgeProps) {
  return (
    <View style={styles.dateBadge}>
      <Text style={styles.dateBadgeText}>{formatLogicalDateBadge(logicalDate)}</Text>
    </View>
  );
}

// UI-005~UI-009 공통 상단 영역: 날짜 배지(+선택적 경고 배지) → 제목 → 선택적 설명.
// FINALIZING(UI-010)은 이 헤더를 쓰지 않는 완전히 다른 전체화면 레이아웃이라 별도 컴포넌트(FinalizingView)로 둔다.
// showShopIcon=false와 titleStyle/descriptionStyle은 UI_REFERENCE.md 2절 예외(UI-008·UI-009, DEADLINE_WARNING)에서만 쓴다.
export function HomeHeader({
  logicalDate,
  badgeLabel,
  nickname,
  title,
  feedback,
  description,
  showShopIcon = true,
  titleStyle,
  descriptionStyle,
  descriptionNumberOfLines,
}: HomeHeaderProps) {
  const trimmedNickname = nickname?.trim();
  const greeting = nickname !== undefined ? (trimmedNickname ? `${trimmedNickname}님,` : '안녕하세요,') : null;
  const [headerContentHeight, setHeaderContentHeight] = useState(0);
  const [isShopModalVisible, setIsShopModalVisible] = useState(false);

  return (
    <View style={styles.container}>
      <View style={styles.headerRow}>
        <View
          style={styles.headerContent}
          onLayout={({ nativeEvent }) => {
            const nextHeight = nativeEvent.layout.height;
            if (nextHeight !== headerContentHeight) {
              setHeaderContentHeight(nextHeight);
            }
          }}>
          <View style={styles.badgeRow}>
            <HomeDateBadge logicalDate={logicalDate} />
            {badgeLabel ? (
              <View style={styles.warningBadge}>
                <Text style={styles.warningBadgeText}>{badgeLabel}</Text>
              </View>
            ) : null}
          </View>
          <Text style={[styles.title, titleStyle]}>
            {greeting ? `${greeting}\n` : ''}
            {title}
          </Text>
          {feedback ? (
            <Text
              adjustsFontSizeToFit
              minimumFontScale={0.65}
              numberOfLines={1}
              style={[
                styles.feedback,
                feedback.length > 28
                  ? styles.feedbackTight
                  : feedback.length > 22
                    ? styles.feedbackCompact
                    : null,
              ]}>
              {feedback}
            </Text>
          ) : null}
          {description ? (
            <Text style={[styles.description, descriptionStyle]} numberOfLines={descriptionNumberOfLines}>
              {description}
            </Text>
          ) : null}
        </View>
        {showShopIcon ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="상점 안내 열기"
            hitSlop={spacing.sm}
            onPress={() => setIsShopModalVisible(true)}
            style={styles.shopButton}>
            <Image
              accessibilityIgnoresInvertColors
              source={SHOP_ICON_SOURCE}
              resizeMode="contain"
              style={[
                styles.shopIcon,
                headerContentHeight > 0
                  ? { height: headerContentHeight *0.9, opacity: 1 }
                  : null,
              ]}
            />
          </Pressable>
        ) : null}
      </View>
      {showShopIcon ? (
        <ShopComingSoonModal
          visible={isShopModalVisible}
          onClose={() => setIsShopModalVisible(false)}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg + 4,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    position: 'relative',
  },
  headerContent: {
    flex: 1,
    minWidth: 0,
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
    fontFamily: fonts.bold,
  },
  warningBadge: {
    backgroundColor: colors.deadlineBadgeBackground,
    borderColor: colors.deadlineBadgeText,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
  },
  warningBadgeText: {
    ...typography.caption,
    color: colors.deadlineBadgeText,
    fontFamily: fonts.bold,
  },
  title: {
    ...typography.title,
    color: colors.text,
    fontSize: 17,
    marginLeft: 8,
  },
  feedback: {
    ...typography.title,
    color: colors.text,
    fontSize: 17,
    marginLeft: 8,
  },
  feedbackCompact: {
    fontSize: 14,
  },
  feedbackTight: {
    fontSize: 12,
  },
  description: {
    ...typography.body,
    color: colors.textSecondary,
    marginTop: spacing.xs,
  },
  shopButton: {
    position: 'absolute',
    right: -30,
    top: 6,
  },
  shopIcon: {
    height: 1,
    aspectRatio: 159 / 228,
    opacity: 0,
  },
});

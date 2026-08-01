import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, spacing, typography } from '@/src/constants/tokens';

type ShopComingSoonModalProps = {
  visible: boolean;
  onClose: () => void;
};

export function ShopComingSoonModal({ visible, onClose }: ShopComingSoonModalProps) {
  return (
    <Modal
      transparent
      animationType="fade"
      visible={visible}
      onRequestClose={onClose}
      statusBarTranslucent>
      <Pressable
        accessibilityLabel="상점 안내 닫기"
        accessible={false}
        onPress={onClose}
        style={styles.backdrop}>
        <Pressable
          accessible={false}
          onPress={(event) => event.stopPropagation()}
          style={styles.dialog}>
          <View style={styles.body}>
            <Text style={styles.title}>상점은 아직 준비 중이에요</Text>
            <Text style={styles.description}>
              이번 MVP 버전에서는 상점 기능을 이용할 수 없어요. 추후 업데이트에서 만나보실 수 있습니다.
            </Text>
          </View>
          <Pressable accessibilityRole="button" onPress={onClose} style={styles.confirmButton}>
            <Text style={styles.confirmText}>확인</Text>
          </Pressable>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
    backgroundColor: 'rgba(17, 24, 39, 0.35)',
  },
  dialog: {
    backgroundColor: colors.surface,
    borderRadius: 20,
    overflow: 'hidden',
  },
  body: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.xl,
    alignItems: 'center',
  },
  title: {
    ...typography.title,
    color: colors.text,
    textAlign: 'center',
  },
  description: {
    ...typography.body,
    color: colors.textSecondary,
    textAlign: 'center',
    marginTop: spacing.md,
  },
  confirmButton: {
    minHeight: 56,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.primary,
  },
  confirmText: {
    ...typography.body,
    color: colors.background,
    fontWeight: '700',
  },
});

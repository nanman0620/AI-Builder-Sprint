import { ActivityIndicator, Modal, Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, fonts, spacing, typography } from '@/src/constants/tokens';

type ExitConfirmationModalProps = {
  visible: boolean;
  isDeleting: boolean;
  error: string | null;
  onContinue: () => void;
  onDelete: () => void;
};

export function ExitConfirmationModal({
  visible,
  isDeleting,
  error,
  onContinue,
  onDelete,
}: ExitConfirmationModalProps) {
  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={() => {
        if (!isDeleting) {
          onContinue();
        }
      }}>
      <View style={styles.backdrop}>
        <View style={styles.dialog}>
          <View style={styles.body}>
            <Text style={styles.title}>작성 중인 내용이 있어요.</Text>
            <Text style={styles.description}>
              지금 나가면 입력한 내용과 확인 중인 항목이 모두 삭제돼요.
            </Text>
            {error ? (
              <Text style={styles.error}>
                정보를 불러오지 못했어요.{'\n'}잠시 후 다시 시도해 주세요.
              </Text>
            ) : null}
          </View>
          <View style={styles.actions}>
            <Pressable style={styles.action} onPress={onContinue} disabled={isDeleting}>
              <Text style={styles.continueText}>계속 작성하기</Text>
            </Pressable>
            <Pressable style={[styles.action, styles.deleteAction]} onPress={onDelete} disabled={isDeleting}>
              {isDeleting ? (
                <ActivityIndicator color={colors.error} />
              ) : (
                <Text style={styles.deleteText}>{error ? '다시 시도' : '내용 삭제하고 나가기'}</Text>
              )}
            </Pressable>
          </View>
        </View>
      </View>
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
    ...typography.caption,
    color: colors.textSecondary,
    textAlign: 'center',
    marginTop: spacing.md,
  },
  error: {
    ...typography.caption,
    color: colors.error,
    textAlign: 'center',
    marginTop: spacing.md,
  },
  actions: {
    flexDirection: 'row',
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  action: {
    flex: 1,
    minHeight: 64,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.sm,
  },
  deleteAction: {
    borderLeftWidth: 1,
    borderLeftColor: colors.border,
  },
  continueText: {
    ...typography.body,
    color: colors.textSecondary,
    fontFamily: fonts.bold,
    textAlign: 'center',
  },
  deleteText: {
    ...typography.body,
    color: colors.error,
    fontFamily: fonts.bold,
    textAlign: 'center',
  },
});

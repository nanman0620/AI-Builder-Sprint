import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, fonts, spacing, typography } from '@/src/constants/tokens';

type LogoutConfirmModalProps = {
  visible: boolean;
  loading?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
};

export function LogoutConfirmModal({ visible, loading = false, onCancel, onConfirm }: LogoutConfirmModalProps) {
  return (
    <Modal transparent animationType="fade" visible={visible} onRequestClose={onCancel} statusBarTranslucent>
      <View style={styles.overlay}>
        <View style={styles.card}>
          <Text style={styles.title}>로그아웃하시겠어요?</Text>
          <Text style={styles.description}>
            현재 계정에서 로그아웃하고
            {'\n'}로그인 화면으로 이동합니다.
          </Text>
          <View style={styles.buttonRow}>
            <Pressable style={[styles.cancelButton, styles.buttonMargin]} onPress={onCancel} disabled={loading}>
              <Text style={styles.cancelText}>취소</Text>
            </Pressable>
            <Pressable style={[styles.confirmButton, loading ? styles.buttonDisabled : null]} onPress={onConfirm} disabled={loading}>
              <Text style={styles.confirmText}>로그아웃</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.35)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: spacing.lg,
  },
  card: {
    width: '100%',
    backgroundColor: colors.background,
    borderRadius: 20,
    padding: spacing.lg,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.08,
    shadowRadius: 20,
    elevation: 10,
  },
  title: {
    ...typography.title,
    marginBottom: spacing.sm,
    color: colors.text,
  },
  description: {
    ...typography.body,
    color: colors.textSecondary,
    marginBottom: spacing.lg,
    lineHeight: 22,
  },
  buttonRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  buttonMargin: {
    marginRight: spacing.sm,
  },
  cancelButton: {
    flex: 1,
    height: 46,
    borderRadius: 12,
    backgroundColor: colors.border,
    justifyContent: 'center',
    alignItems: 'center',
  },
  confirmButton: {
    flex: 1,
    height: 46,
    borderRadius: 12,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  cancelText: {
    ...typography.body,
    fontFamily: fonts.bold,
    color: colors.text,
  },
  confirmText: {
    ...typography.body,
    fontFamily: fonts.bold,
    color: colors.background,
  },
});

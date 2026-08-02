import { StyleSheet, View } from 'react-native';

import { colors } from '@/src/constants/tokens';

import type { CheckInPlanBlockSummary } from '../types';
import { CheckInPlanRow } from './check-in-plan-row';

type CheckInPlanListProps = {
  plans: CheckInPlanBlockSummary[];
};

const CARD_PADDING = 16;

export function CheckInPlanList({ plans }: CheckInPlanListProps) {
  return (
    <View style={styles.card}>
      <View style={styles.content}>
        {plans.map((plan) => (
          <CheckInPlanRow
            key={plan.id}
            displayTitle={plan.displayTitle}
            completed={plan.status === 'COMPLETED'}
          />
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    marginHorizontal: 16,
    padding: CARD_PADDING,
    borderWidth: 1,
    borderColor: colors.checkInListBorder,
    borderRadius: 24,
    backgroundColor: colors.surface,
  },
  content: {
    gap: 14,
  },
});

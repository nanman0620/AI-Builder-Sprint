import { MaterialIcons } from '@expo/vector-icons';
import { ScrollView, Pressable, StyleSheet, Text, View } from 'react-native';

import { ErrorView } from '@/src/components/common/error-view';
import { LoadingView } from '@/src/components/common/loading-view';
import { colors, fonts, spacing, typography } from '@/src/constants/tokens';

import { useCalendar } from '../hooks/use-calendar';
import {
  formatSegmentTime,
  getCompletedCount,
  getVisibleCheckIn,
  getVisiblePlanBlocks,
  hasDayData,
  hasOnlyFuturePeriods,
  isDayEmpty,
  listMonthDates,
  sortFixedSchedules,
  sortPeriods,
} from '../logic';
import type { CalendarDay, CalendarPeriodData, CalendarResponse } from '../types';

const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'];
const PERIOD_LABELS = {
  MORNING: '오전',
  AFTERNOON: '오후',
  EVENING: '저녁',
} as const;

function parseDateParts(date: string) {
  const [year, month, day] = date.split('-').map(Number);
  return { year, month, day };
}

function MonthCalendar({
  data,
  selectedDate,
  disabled,
  onSelect,
  onMove,
}: {
  data: CalendarResponse;
  selectedDate: string;
  disabled: boolean;
  onSelect: (date: string) => void;
  onMove: (offset: -1 | 1) => void;
}) {
  const dates = listMonthDates(data);
  const first = parseDateParts(data.from);
  const leadingBlanks = new Date(first.year, first.month - 1, 1).getDay();
  const dayByDate = new Map(data.days.map((day) => [day.date, day]));

  return (
    <View>
      <View style={styles.monthHeader}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="이전 달"
          disabled={disabled}
          hitSlop={12}
          onPress={() => onMove(-1)}>
          <MaterialIcons name="chevron-left" size={28} color={colors.textSecondary} />
        </Pressable>
        <Text style={styles.monthTitle}>{`${first.year}년 ${first.month}월`}</Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="다음 달"
          disabled={disabled}
          hitSlop={12}
          onPress={() => onMove(1)}>
          <MaterialIcons name="chevron-right" size={28} color={colors.textSecondary} />
        </Pressable>
      </View>

      <View style={styles.weekRow}>
        {WEEKDAYS.map((weekday) => (
          <Text key={weekday} style={styles.weekday}>
            {weekday}
          </Text>
        ))}
      </View>

      <View style={styles.daysGrid}>
        {Array.from({ length: leadingBlanks }, (_, index) => (
          <View key={`blank-${index}`} style={styles.dayCell} />
        ))}
        {dates.map((date) => {
          const day = dayByDate.get(date);
          const selected = date === selectedDate;
          const dateNumber = Number(date.slice(-2));
          return (
            <Pressable
              key={date}
              accessibilityRole="button"
              accessibilityLabel={`${dateNumber}일`}
              style={styles.dayCell}
              onPress={() => onSelect(date)}>
              <View style={[styles.dayNumberCircle, selected && styles.dayNumberCircleSelected]}>
                <Text style={[styles.dayNumber, selected && styles.dayNumberSelected]}>{dateNumber}</Text>
              </View>
              {hasDayData(day) ? <View style={styles.dayDot} /> : null}
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

function PlanBlockRow({
  title,
  completed,
}: {
  title: string;
  completed: boolean;
}) {
  return (
    <View style={[styles.planRow, completed && styles.planRowCompleted]}>
      <View style={[styles.statusCircle, completed && styles.statusCircleCompleted]}>
        {completed ? <MaterialIcons name="check" size={16} color={colors.background} /> : null}
      </View>
      <Text style={styles.planTitle}>{title}</Text>
    </View>
  );
}

function PeriodSection({ period }: { period: CalendarPeriodData }) {
  const checkIn = getVisibleCheckIn(period);
  const blocks = getVisiblePlanBlocks(period);
  const schedules = sortFixedSchedules(period.fixedSchedules);
  if (!checkIn && blocks.length === 0 && schedules.length === 0) {
    return null;
  }

  return (
    <View style={styles.periodGroup}>
      <View style={[styles.periodHeader, checkIn && styles.periodHeaderWithScore]}>
        <Text style={styles.periodTitle}>
          {PERIOD_LABELS[period.period]}
          {checkIn ? ` · ${checkIn.score}점` : ''}
        </Text>
        {checkIn ? (
          <View style={styles.scoreCircle}>
            <Text style={styles.scoreText}>{checkIn.score}</Text>
          </View>
        ) : null}
      </View>

      {schedules.map((schedule) => (
        <View key={schedule.id} style={styles.scheduleCard}>
          <Text style={styles.scheduleHeading}>고정일정</Text>
          <View style={styles.scheduleContent}>
            <Text style={styles.scheduleTitle}>• {schedule.title}</Text>
            <Text style={styles.scheduleTime}>
              {formatSegmentTime(schedule.segmentStartAt)} ~ {formatSegmentTime(schedule.segmentEndAt)}
            </Text>
          </View>
        </View>
      ))}

      {blocks.map((block) => (
        <PlanBlockRow
          key={block.id}
          title={block.displayTitle}
          completed={block.status === 'COMPLETED' || block.status === 'CHECKED'}
        />
      ))}
    </View>
  );
}

function DayDetail({ date, day }: { date: string; day: CalendarDay | undefined }) {
  const { month, day: dateNumber } = parseDateParts(date);
  const hideStats = hasOnlyFuturePeriods(day);
  const completedCount = getCompletedCount(day);

  return (
    <View style={styles.detail}>
      <View style={styles.detailHeader}>
        <Text style={styles.detailTitle}>{`${month}월 ${dateNumber}일 기록`}</Text>
        {!hideStats && !isDayEmpty(day) ? (
          <Text style={styles.completedCount}>{completedCount}개 완료</Text>
        ) : null}
      </View>

      {isDayEmpty(day) ? (
        <View style={styles.empty}>
          <Text style={styles.emptyText}>이 날짜에는 표시할 계획이 없어요.</Text>
        </View>
      ) : (
        sortPeriods(day?.periods ?? []).map((period) => (
          <PeriodSection key={period.period} period={period} />
        ))
      )}
    </View>
  );
}

export function CalendarScreen() {
  const { data, selectedDate, selectDate, isLoading, refreshError, moveMonth, retry } = useCalendar();

  if (!data && isLoading) {
    return <LoadingView />;
  }
  if (!data) {
    return <ErrorView onRetry={retry} />;
  }

  const selected = selectedDate ?? data.logicalToday;
  const selectedDay = data.days.find((day) => day.date === selected);

  return (
    <View style={styles.screen}>
      {refreshError ? (
        <View style={styles.refreshError}>
          <Text style={styles.refreshErrorText}>
            정보를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.
          </Text>
          <Pressable disabled={isLoading} onPress={retry}>
            <Text style={styles.retryText}>다시 시도</Text>
          </Pressable>
        </View>
      ) : null}
      <ScrollView contentContainerStyle={styles.content}>
        <MonthCalendar
          data={data}
          selectedDate={selected}
          disabled={isLoading}
          onSelect={selectDate}
          onMove={moveMonth}
        />
        <DayDetail date={selected} day={selectedDay} />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  content: { paddingHorizontal: spacing.lg, paddingTop: spacing.xl, paddingBottom: spacing.xl },
  refreshError: {
    backgroundColor: colors.primarySoft,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  refreshErrorText: { ...typography.caption, color: colors.text, flex: 1 },
  retryText: { ...typography.caption, color: colors.primary, fontFamily: fonts.bold },
  monthHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.lg,
  },
  monthTitle: { ...typography.title, color: colors.text },
  weekRow: { flexDirection: 'row', marginBottom: spacing.sm },
  weekday: {
    ...typography.caption,
    color: colors.textSecondary,
    fontFamily: fonts.bold,
    textAlign: 'center',
    width: `${100 / 7}%`,
  },
  daysGrid: { flexDirection: 'row', flexWrap: 'wrap' },
  dayCell: { width: `${100 / 7}%`, height: 54, alignItems: 'center', justifyContent: 'flex-start' },
  dayNumberCircle: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dayNumberCircleSelected: { backgroundColor: colors.primary },
  dayNumber: { ...typography.body, color: colors.text },
  dayNumberSelected: { color: colors.background, fontFamily: fonts.bold },
  dayDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.primary, marginTop: 2 },
  detail: { marginTop: spacing.lg },
  detailHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.md,
  },
  detailTitle: { ...typography.title, color: colors.text },
  completedCount: { ...typography.body, color: colors.primary, fontFamily: fonts.bold },
  periodGroup: { gap: spacing.sm, marginBottom: spacing.md },
  periodHeader: {
    minHeight: 56,
    borderWidth: 2,
    borderColor: colors.textSecondary,
    borderRadius: 16,
    paddingHorizontal: spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  periodHeaderWithScore: { borderColor: colors.primary },
  periodTitle: { ...typography.body, color: colors.text, fontFamily: fonts.bold },
  scoreCircle: {
    width: 36,
    height: 36,
    borderRadius: 18,
    borderWidth: 5,
    borderColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  scoreText: { ...typography.caption, color: colors.primary, fontFamily: fonts.bold },
  scheduleCard: {
    borderWidth: 2,
    borderColor: colors.primary,
    borderRadius: 16,
    backgroundColor: colors.primarySoft,
    padding: spacing.md,
  },
  scheduleHeading: { ...typography.body, color: colors.text, fontFamily: fonts.bold, marginBottom: spacing.sm },
  scheduleContent: { flexDirection: 'row', justifyContent: 'space-between', gap: spacing.sm },
  scheduleTitle: { ...typography.body, color: colors.text, flex: 1 },
  scheduleTime: { ...typography.body, color: colors.textSecondary },
  planRow: {
    minHeight: 56,
    borderWidth: 2,
    borderColor: colors.textSecondary,
    borderRadius: 14,
    paddingHorizontal: spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  planRowCompleted: { borderColor: colors.primary, backgroundColor: colors.primarySoft },
  statusCircle: {
    width: 28,
    height: 28,
    borderRadius: 14,
    borderWidth: 2,
    borderColor: colors.textSecondary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  statusCircleCompleted: { borderColor: colors.primary, backgroundColor: colors.primary },
  planTitle: { ...typography.body, color: colors.text, flex: 1 },
  empty: { minHeight: 260, alignItems: 'center', justifyContent: 'center' },
  emptyText: { ...typography.title, color: colors.text, textAlign: 'center' },
});

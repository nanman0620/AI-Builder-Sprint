import { ErrorView } from '@/src/components/common/error-view';
import { LoadingView } from '@/src/components/common/loading-view';
import { RoutePlaceholder } from '@/src/components/common/route-placeholder';

import { CollectingScreen } from '../components/collecting-screen';
import { EntryScreen } from '../components/entry-screen';
import { usePlanManagement } from '../hooks/use-plan-management';

const NEW_CYCLE_EXAMPLES = [
  '금요일까지 자료구조 과제 3문제',
  '토요일 9시부터 18시까지 알바',
  '단어 공부 3일 동안 매일 30개',
];

const ACTIVE_CYCLE_EXAMPLES = [
  '자료구조 과제 양이 6문제로 바뀌었어',
  '토요일 17시부터 21시까지로 알바 일정이 바뀌었어',
  '매일 오전에 러닝 30분씩 할래',
];

export function PlanManagementScreen() {
  const { state, isLoading, hasLoadError, actionError, isSubmitting, reload, submitInitialMessage, sendAnswer } =
    usePlanManagement();

  if (!state && isLoading) {
    return <LoadingView />;
  }

  if (!state && hasLoadError) {
    return <ErrorView onRetry={reload} />;
  }

  if (!state) {
    return <LoadingView />;
  }

  switch (state.screenMode) {
    case 'NEW_CYCLE_ENTRY':
      return (
        <EntryScreen
          title="오늘부터 새로운 7일을 이어볼까요?"
          examples={NEW_CYCLE_EXAMPLES}
          isSubmitting={isSubmitting}
          onSubmit={(message) => submitInitialMessage('NEW_CYCLE', message)}
        />
      );
    case 'ACTIVE_CYCLE_ENTRY':
      return (
        <EntryScreen
          title="수정하거나 추가할 항목이 있나요?"
          examples={ACTIVE_CYCLE_EXAMPLES}
          isSubmitting={isSubmitting}
          onSubmit={(message) => submitInitialMessage('ACTIVE_CYCLE', message)}
        />
      );
    case 'COLLECTING':
      return (
        <CollectingScreen
          request={state.request}
          isSubmitting={isSubmitting}
          actionError={actionError}
          onSendMessage={sendAnswer}
        />
      );
    case 'CHANGE_CONFIRMATION':
    case 'CHANGE_INPUT':
    case 'FINAL_REVIEW':
    case 'EXECUTING':
    case 'EXECUTION_SUCCESS':
    case 'EXECUTION_FAILED':
      // FE-03 범위 밖. 같은 /plan-management Route 안에서 후속 Issue가 이어서 구현한다.
      return (
        <RoutePlaceholder
          title="계획관리"
          description={`${state.screenMode} 화면은 후속 Issue에서 구현됩니다.`}
        />
      );
    default: {
      const exhaustiveCheck: never = state;
      return exhaustiveCheck;
    }
  }
}

import { useFocusEffect, useNavigation, usePreventRemove } from '@react-navigation/native';
import { useRouter } from 'expo-router';
import { useCallback, useEffect } from 'react';
import { BackHandler } from 'react-native';

import { ErrorView } from '@/src/components/common/error-view';
import { LoadingView } from '@/src/components/common/loading-view';
import { RoutePlaceholder } from '@/src/components/common/route-placeholder';

import { ChangeConfirmationScreen } from '../components/change-confirmation-screen';
import { ChangeInputScreen } from '../components/change-input-screen';
import { CollectingScreen } from '../components/collecting-screen';
import { EntryScreen } from '../components/entry-screen';
import { ExitConfirmationModal } from '../components/exit-confirmation-modal';
import { FinalReviewScreen } from '../components/final-review-screen';
import { usePlanExitGuard } from '../contexts/plan-exit-guard-context';
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
  const router = useRouter();
  const navigation = useNavigation();
  const {
    isGuardActive,
    pendingDestination,
    setGuardActive,
    requestExit,
    dismissExit,
    completeExit,
  } = usePlanExitGuard();
  const {
    state,
    isLoading,
    hasLoadError,
    actionError,
    exitError,
    isSubmitting,
    reload,
    submitInitialMessage,
    sendAnswer,
    submitDecision,
    reopenRequest,
    deleteCurrentRequest,
    clearExitError,
  } = usePlanManagement();

  const isProtectedDraft =
    !!state?.request &&
    (state.screenMode === 'COLLECTING' ||
      state.screenMode === 'CHANGE_CONFIRMATION' ||
      state.screenMode === 'CHANGE_INPUT' ||
      state.screenMode === 'FINAL_REVIEW');

  useEffect(() => {
    setGuardActive(isProtectedDraft);
    return () => setGuardActive(false);
  }, [isProtectedDraft, setGuardActive]);

  usePreventRemove(isProtectedDraft, ({ data }) => {
    requestExit('back', () => navigation.dispatch(data.action));
  });

  useFocusEffect(
    useCallback(() => {
      if (!isProtectedDraft) {
        return;
      }
      const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
        requestExit('back', () => router.back());
        return true;
      });
      return () => subscription.remove();
    }, [isProtectedDraft, requestExit, router])
  );

  const handleDismissExit = () => {
    clearExitError();
    dismissExit();
  };

  const handleDeleteAndExit = async () => {
    const deleted = await deleteCurrentRequest();
    if (deleted) {
      completeExit();
    }
  };

  if (!state && isLoading) {
    return <LoadingView />;
  }

  if (!state && hasLoadError) {
    return <ErrorView onRetry={reload} />;
  }

  if (!state) {
    return <LoadingView />;
  }

  let content: React.ReactNode;

  switch (state.screenMode) {
    case 'NEW_CYCLE_ENTRY':
      content = (
        <EntryScreen
          title="오늘부터 새로운 7일을 이어볼까요?"
          examples={NEW_CYCLE_EXAMPLES}
          isSubmitting={isSubmitting}
          onSubmit={(message) => submitInitialMessage('NEW_CYCLE', message)}
        />
      );
      break;
    case 'ACTIVE_CYCLE_ENTRY':
      content = (
        <EntryScreen
          title="수정하거나 추가할 항목이 있나요?"
          examples={ACTIVE_CYCLE_EXAMPLES}
          isSubmitting={isSubmitting}
          onSubmit={(message) => submitInitialMessage('ACTIVE_CYCLE', message)}
        />
      );
      break;
    case 'COLLECTING':
      content = (
        <CollectingScreen
          request={state.request}
          isSubmitting={isSubmitting}
          actionError={actionError}
          onSendMessage={sendAnswer}
        />
      );
      break;
    case 'CHANGE_CONFIRMATION':
      content = (
        <ChangeConfirmationScreen
          request={state.request}
          isSubmitting={isSubmitting}
          actionError={actionError}
          onDecision={submitDecision}
        />
      );
      break;
    case 'CHANGE_INPUT':
      content = (
        <ChangeInputScreen
          request={state.request}
          isSubmitting={isSubmitting}
          actionError={actionError}
          onSendMessage={sendAnswer}
        />
      );
      break;
    case 'FINAL_REVIEW':
      content = (
        <FinalReviewScreen
          request={state.request}
          isSubmitting={isSubmitting}
          actionError={actionError}
          onReload={reload}
          onReopen={reopenRequest}
        />
      );
      break;
    case 'EXECUTING':
    case 'EXECUTION_SUCCESS':
    case 'EXECUTION_FAILED':
      // FE-05 범위. 같은 /plan-management Route 안에서 후속 Issue가 이어서 구현한다.
      content = (
        <RoutePlaceholder
          title="계획관리"
          description={`${state.screenMode} 화면은 후속 Issue에서 구현됩니다.`}
        />
      );
      break;
    default: {
      const exhaustiveCheck: never = state;
      return exhaustiveCheck;
    }
  }

  return (
    <>
      {content}
      <ExitConfirmationModal
        visible={isGuardActive && pendingDestination !== null}
        isDeleting={isSubmitting}
        error={exitError}
        onContinue={handleDismissExit}
        onDelete={handleDeleteAndExit}
      />
    </>
  );
}

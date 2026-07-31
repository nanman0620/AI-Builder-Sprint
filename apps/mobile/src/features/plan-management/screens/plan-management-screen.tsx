import { useFocusEffect, useNavigation, usePreventRemove } from '@react-navigation/native';
import { useRouter } from 'expo-router';
import { useCallback, useEffect, useRef } from 'react';
import { BackHandler } from 'react-native';

import { ErrorView } from '@/src/components/common/error-view';
import { LoadingView } from '@/src/components/common/loading-view';

import { ChangeConfirmationScreen } from '../components/change-confirmation-screen';
import { ChangeInputScreen } from '../components/change-input-screen';
import { CollectingScreen } from '../components/collecting-screen';
import { EntryScreen } from '../components/entry-screen';
import { ExecutionFailedScreen } from '../components/execution-failed-screen';
import { ExecutionSuccessScreen } from '../components/execution-success-screen';
import { ExecutingScreen } from '../components/executing-screen';
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
  const allowResultExitRef = useRef(false);
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
    executionRefreshError,
    isExecutionRefreshing,
    isSubmitting,
    reload,
    submitInitialMessage,
    sendAnswer,
    submitDecision,
    reopenRequest,
    executeRequest,
    refreshExecution,
    retryExecution,
    acknowledgeExecutionResult,
    cancelFailedRequest,
    deleteCurrentRequest,
    clearExitError,
  } = usePlanManagement();

  const isProtectedDraft =
    !!state?.request &&
    (state.screenMode === 'COLLECTING' ||
      state.screenMode === 'CHANGE_CONFIRMATION' ||
      state.screenMode === 'CHANGE_INPUT' ||
      state.screenMode === 'FINAL_REVIEW');
  const isBlockingResult =
    state?.screenMode === 'EXECUTION_SUCCESS' ||
    state?.screenMode === 'EXECUTION_FAILED';

  // 성공·실패 결과는 계획관리 탭이 포커스된 동안만 탭 바를 숨긴다.
  // EXECUTING과 기존 작성 상태는 기존 탭 바를 그대로 표시한다.
  useFocusEffect(
    useCallback(() => {
      navigation.setOptions({
        tabBarStyle: isBlockingResult ? { display: 'none' } : undefined,
      });
      return () => {
        navigation.setOptions({ tabBarStyle: undefined });
      };
    }, [isBlockingResult, navigation])
  );

  useEffect(() => {
    setGuardActive(isProtectedDraft);
    return () => setGuardActive(false);
  }, [isProtectedDraft, setGuardActive]);

  usePreventRemove(isProtectedDraft || isBlockingResult, ({ data }) => {
    if (isBlockingResult) {
      if (allowResultExitRef.current) {
        navigation.dispatch(data.action);
      }
      return;
    }
    requestExit('back', () => navigation.dispatch(data.action));
  });

  useFocusEffect(
    useCallback(() => {
      if (!isProtectedDraft && !isBlockingResult) {
        return;
      }
      const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
        if (isBlockingResult) {
          return true;
        }
        requestExit('back', () => router.back());
        return true;
      });
      return () => subscription.remove();
    }, [isBlockingResult, isProtectedDraft, requestExit, router])
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

  const handleAcknowledgeResult = async () => {
    const acknowledged = await acknowledgeExecutionResult();
    if (!acknowledged) {
      return;
    }
    allowResultExitRef.current = true;
    // 홈 화면은 탭 포커스 시 기존 useHome 경계에서 GET /home/current를 재호출한다.
    router.replace('/(tabs)/home');
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
          onExecute={executeRequest}
        />
      );
      break;
    case 'EXECUTING':
      content = (
        <ExecutingScreen
          refreshError={executionRefreshError}
          isRefreshing={isExecutionRefreshing}
          onRefresh={() => refreshExecution(state.request.id)}
        />
      );
      break;
    case 'EXECUTION_SUCCESS':
      content = (
        <ExecutionSuccessScreen
          result={state.request.execution?.executionResult ?? null}
          isSubmitting={isSubmitting}
          error={actionError}
          onAcknowledge={handleAcknowledgeResult}
        />
      );
      break;
    case 'EXECUTION_FAILED':
      content = (
        <ExecutionFailedScreen
          message={
            state.request.execution?.error?.message ??
            '계획을 반영하는 중 문제가 발생했어요.'
          }
          isSubmitting={isSubmitting}
          actionError={actionError}
          onRetry={retryExecution}
          onCancel={cancelFailedRequest}
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

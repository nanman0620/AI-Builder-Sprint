// 순수 함수 테스트. RN 의존성이 없어 apps/mobile/src/features/home/logic.test.ts와 동일하게
// 로컬 tsc로 CommonJS로 컴파일한 뒤 node --test로 실행한다.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { performAccountWithdrawal, type AccountWithdrawalDeps } from './account-withdrawal-flow';

type CallLog = string[];

function makeDeps(overrides: Partial<AccountWithdrawalDeps> & { callLog: CallLog }): AccountWithdrawalDeps {
  const { callLog, ...rest } = overrides;
  const defaults: AccountWithdrawalDeps = {
    deleteAccount: async () => {
      callLog.push('deleteAccount');
    },
    signOutLocal: async () => {
      callLog.push('signOutLocal');
    },
    forceClearLocalSession: async () => {
      callLog.push('forceClearLocalSession');
    },
    isLocalSessionCleared: async () => {
      callLog.push('isLocalSessionCleared');
      return true;
    },
    clearAllLocalData: async () => {
      callLog.push('clearAllLocalData');
    },
    resetAppSync: () => {
      callLog.push('resetAppSync');
    },
    resetBootstrap: () => {
      callLog.push('resetBootstrap');
    },
    onSuccess: () => {
      callLog.push('onSuccess');
    },
    onAuthDeletionFailed: () => {
      callLog.push('onAuthDeletionFailed');
    },
    onGenericError: () => {
      callLog.push('onGenericError');
    },
    onLocalSessionCleanupFailed: () => {
      callLog.push('onLocalSessionCleanupFailed');
    },
  };
  return { ...defaults, ...rest };
}

test('일반 오류(code 없음)는 onGenericError만 호출하고 나머지는 전부 건너뛴다', async () => {
  const callLog: CallLog = [];
  await performAccountWithdrawal(
    makeDeps({
      callLog,
      deleteAccount: async () => {
        callLog.push('deleteAccount');
        throw new Error('network down');
      },
    })
  );

  assert.deepEqual(callLog, ['deleteAccount', 'onGenericError']);
});

test('ACCOUNT_AUTH_DELETION_FAILED 오류는 onAuthDeletionFailed만 호출한다', async () => {
  const callLog: CallLog = [];
  await performAccountWithdrawal(
    makeDeps({
      callLog,
      deleteAccount: async () => {
        callLog.push('deleteAccount');
        throw { code: 'ACCOUNT_AUTH_DELETION_FAILED' };
      },
    })
  );

  assert.deepEqual(callLog, ['deleteAccount', 'onAuthDeletionFailed']);
});

test('성공 + signOutLocal 성공이면 검증 단계(forceClearLocalSession 등)를 전부 건너뛰고 성공 처리한다', async () => {
  const callLog: CallLog = [];
  await performAccountWithdrawal(makeDeps({ callLog }));

  assert.deepEqual(callLog, ['deleteAccount', 'signOutLocal', 'resetAppSync', 'resetBootstrap', 'onSuccess']);
});

test('성공 + signOutLocal 실패 + forceClearLocalSession 이후 세션이 지워졌으면 성공 처리한다', async () => {
  const callLog: CallLog = [];
  await performAccountWithdrawal(
    makeDeps({
      callLog,
      signOutLocal: async () => {
        callLog.push('signOutLocal');
        throw new Error('signOut failed');
      },
    })
  );

  assert.deepEqual(callLog, [
    'deleteAccount',
    'signOutLocal',
    'forceClearLocalSession',
    'isLocalSessionCleared',
    'resetAppSync',
    'resetBootstrap',
    'onSuccess',
  ]);
});

test('1차 재조회가 false면 clearAllLocalData까지 시도하고, 2차 재조회가 true면 성공 처리한다', async () => {
  const callLog: CallLog = [];
  let isClearedCallCount = 0;
  await performAccountWithdrawal(
    makeDeps({
      callLog,
      signOutLocal: async () => {
        callLog.push('signOutLocal');
        throw new Error('signOut failed');
      },
      isLocalSessionCleared: async () => {
        isClearedCallCount += 1;
        callLog.push(`isLocalSessionCleared:${isClearedCallCount}`);
        return isClearedCallCount >= 2; // 1차는 false, 2차는 true
      },
    })
  );

  assert.deepEqual(callLog, [
    'deleteAccount',
    'signOutLocal',
    'forceClearLocalSession',
    'isLocalSessionCleared:1',
    'clearAllLocalData',
    'isLocalSessionCleared:2',
    'resetAppSync',
    'resetBootstrap',
    'onSuccess',
  ]);
});

test('1차·2차 재조회가 모두 false면 onLocalSessionCleanupFailed만 호출하고 성공 처리하지 않는다', async () => {
  const callLog: CallLog = [];
  await performAccountWithdrawal(
    makeDeps({
      callLog,
      signOutLocal: async () => {
        callLog.push('signOutLocal');
        throw new Error('signOut failed');
      },
      isLocalSessionCleared: async () => {
        callLog.push('isLocalSessionCleared');
        return false;
      },
    })
  );

  assert.deepEqual(callLog, [
    'deleteAccount',
    'signOutLocal',
    'forceClearLocalSession',
    'isLocalSessionCleared',
    'clearAllLocalData',
    'isLocalSessionCleared',
    'onLocalSessionCleanupFailed',
  ]);
});

test('forceClearLocalSession·clearAllLocalData 자체가 예외를 던져도 재조회로 최종 판정한다', async () => {
  const callLog: CallLog = [];
  await performAccountWithdrawal(
    makeDeps({
      callLog,
      signOutLocal: async () => {
        callLog.push('signOutLocal');
        throw new Error('signOut failed');
      },
      forceClearLocalSession: async () => {
        callLog.push('forceClearLocalSession');
        throw new Error('storage broken');
      },
      clearAllLocalData: async () => {
        callLog.push('clearAllLocalData');
        throw new Error('storage still broken');
      },
      isLocalSessionCleared: async () => {
        callLog.push('isLocalSessionCleared');
        return false;
      },
    })
  );

  assert.deepEqual(callLog, [
    'deleteAccount',
    'signOutLocal',
    'forceClearLocalSession',
    'isLocalSessionCleared',
    'clearAllLocalData',
    'isLocalSessionCleared',
    'onLocalSessionCleanupFailed',
  ]);
});

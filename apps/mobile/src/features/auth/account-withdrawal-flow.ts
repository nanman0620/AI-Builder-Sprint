// 회원탈퇴 오케스트레이션 순수 함수. React/RN에 의존하지 않아 apps/mobile/src/features/home/logic.ts와
// 동일한 방식으로 node --test로 검증한다.
//
// 최종 API 명세서는 회원탈퇴를 "시연용 로컬 처리, FastAPI 호출 없음"으로 정하지만, 사용자가
// 명세서 범위를 확인한 뒤 명시적으로 실제 삭제 구현을 요청해 이 흐름이 존재한다
// (docs/ai/AI_USAGE_LOG.md 참고).
//
// 처리 순서: DELETE /me 성공 → signOutLocal 시도 → 실패 시 강제 로컬 세션 제거 → 제거 여부
// 재조회로 검증(실패하면 AsyncStorage.clear()를 최종 수단으로 시도한 뒤 다시 검증) →
// resetAppSync/resetBootstrap → 성공 화면 이동. 검증까지 실패하면 성공 처리하지 않는다 —
// 삭제된 계정의 JWT가 로컬에 남아있으면 만료 전까지 API 요청에 계속 쓰일 수 있기 때문이다
// (get_current_user는 JWT sub만 검증하고 auth.users/user_profiles 존재를 조회하지 않는다).
export type AccountWithdrawalDeps = {
  deleteAccount: () => Promise<void>;
  signOutLocal: () => Promise<void>;
  forceClearLocalSession: () => Promise<void>;
  isLocalSessionCleared: () => Promise<boolean>;
  clearAllLocalData: () => Promise<void>;
  resetAppSync: () => void;
  resetBootstrap: () => void;
  onSuccess: () => void;
  onAuthDeletionFailed: () => void;
  onGenericError: () => void;
  onLocalSessionCleanupFailed: () => void;
};

function isAccountAuthDeletionFailedError(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'code' in error &&
    (error as { code?: unknown }).code === 'ACCOUNT_AUTH_DELETION_FAILED'
  );
}

async function checkSessionCleared(deps: AccountWithdrawalDeps): Promise<boolean> {
  try {
    return await deps.isLocalSessionCleared();
  } catch {
    return false; // 확인 자체가 실패하면 "안 지워짐"으로 취급한다(fail-closed).
  }
}

export async function performAccountWithdrawal(deps: AccountWithdrawalDeps): Promise<void> {
  try {
    await deps.deleteAccount();
  } catch (error) {
    if (isAccountAuthDeletionFailedError(error)) {
      deps.onAuthDeletionFailed();
    } else {
      deps.onGenericError();
    }
    return;
  }

  try {
    await deps.signOutLocal();
  } catch {
    try {
      await deps.forceClearLocalSession();
    } catch {
      // 아래 재조회가 최종 판정한다.
    }

    if (!(await checkSessionCleared(deps))) {
      try {
        await deps.clearAllLocalData();
      } catch {
        // 아래 재조회가 최종 판정한다.
      }

      if (!(await checkSessionCleared(deps))) {
        deps.onLocalSessionCleanupFailed();
        return;
      }
    }
  }

  deps.resetAppSync();
  deps.resetBootstrap();
  deps.onSuccess();
}

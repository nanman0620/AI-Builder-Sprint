import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'expo-router';

import { ErrorView } from '@/src/components/common/error-view';
import { BootstrapSplash } from '@/src/features/bootstrap/components/bootstrap-splash';
import { useBootstrap } from '@/src/features/bootstrap/bootstrap-context';
import { resolveAppRoute } from '@/src/features/bootstrap/route';

type Phase = 'loading' | 'error';

// 앱 최초 실행·완전 재실행 진입점. session 확인 → GET /bootstrap → 최초 Route 판정까지 수행하고
// router.replace로 이동해 이 로고 화면이 뒤로 가기 기록에 남지 않게 한다.
export default function Index() {
  const router = useRouter();
  const { sync } = useBootstrap();
  const [phase, setPhase] = useState<Phase>('loading');
  const [attempt, setAttempt] = useState(0);
  const runIdRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const runId = ++runIdRef.current;

    async function run() {
      setPhase('loading');
      const result = await sync();
      if (cancelled || runId !== runIdRef.current) {
        return;
      }

      const decision = resolveAppRoute(result);
      if (decision.type === 'route') {
        router.replace(decision.href);
        return;
      }

      // 'error' | 'unknown-screen' 모두 전체 오류 화면으로 처리한다.
      setPhase('error');
    }

    run();

    return () => {
      cancelled = true;
    };
  }, [attempt, router, sync]);

  if (phase === 'error') {
    return <ErrorView onRetry={() => setAttempt((n) => n + 1)} />;
  }

  return <BootstrapSplash />;
}

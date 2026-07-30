import { createContext, type PropsWithChildren, useCallback, useContext, useMemo, useRef, useState } from 'react';

export type ExitDestination = 'calendar' | 'home' | 'settings' | 'back';

type PendingExit = {
  destination: ExitDestination;
  proceed: () => void;
};

type PlanExitGuardContextValue = {
  isGuardActive: boolean;
  pendingDestination: ExitDestination | null;
  setGuardActive: (active: boolean) => void;
  requestExit: (destination: ExitDestination, proceed: () => void) => void;
  dismissExit: () => void;
  completeExit: () => void;
};

const PlanExitGuardContext = createContext<PlanExitGuardContextValue | null>(null);

export function PlanExitGuardProvider({ children }: PropsWithChildren) {
  const [isGuardActive, setIsGuardActive] = useState(false);
  const [pendingDestination, setPendingDestination] = useState<ExitDestination | null>(null);
  const isGuardActiveRef = useRef(false);
  const pendingExitRef = useRef<PendingExit | null>(null);

  const setGuardActive = useCallback((active: boolean) => {
    isGuardActiveRef.current = active;
    setIsGuardActive(active);
    if (!active) {
      pendingExitRef.current = null;
      setPendingDestination(null);
    }
  }, []);

  const requestExit = useCallback((destination: ExitDestination, proceed: () => void) => {
    if (!isGuardActiveRef.current) {
      proceed();
      return;
    }
    if (pendingExitRef.current) {
      return;
    }
    pendingExitRef.current = { destination, proceed };
    setPendingDestination(destination);
  }, []);

  const dismissExit = useCallback(() => {
    pendingExitRef.current = null;
    setPendingDestination(null);
  }, []);

  const completeExit = useCallback(() => {
    const pendingExit = pendingExitRef.current;
    if (!pendingExit) {
      return;
    }

    pendingExitRef.current = null;
    isGuardActiveRef.current = false;
    setPendingDestination(null);
    setIsGuardActive(false);
    setTimeout(pendingExit.proceed, 0);
  }, []);

  const value = useMemo(
    () => ({
      isGuardActive,
      pendingDestination,
      setGuardActive,
      requestExit,
      dismissExit,
      completeExit,
    }),
    [completeExit, dismissExit, isGuardActive, pendingDestination, requestExit, setGuardActive]
  );

  return <PlanExitGuardContext.Provider value={value}>{children}</PlanExitGuardContext.Provider>;
}

export function usePlanExitGuard() {
  const context = useContext(PlanExitGuardContext);
  if (!context) {
    throw new Error('usePlanExitGuard must be used within PlanExitGuardProvider.');
  }
  return context;
}

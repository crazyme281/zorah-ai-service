import { useCallback, useEffect, useState } from "react";
import { useAuth } from "./useAuth";
import { getPlan, type PlanStatus } from "../lib/billing";

/**
 * One plan for the whole app. Every screen that calls usePlan() (the top bar,
 * App, Upgrade, Training…) used to fetch /account/plan on its own, each
 * starting out with "no user yet" and "no plan", and a slow or failed fetch
 * in any one of them looked like "plan unknown". Now:
 *   - the last good plan is shared and cached per user,
 *   - simultaneous requests are merged into one,
 *   - a failed refresh never wipes a plan we already know.
 */
let cached: { userId: string; plan: PlanStatus } | null = null;
let inflight: { userId: string; promise: Promise<PlanStatus | null> } | null = null;
let settledUser: string | null = null; // a fetch for this user has finished (even if it failed)
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

function fetchShared(userId: string): Promise<PlanStatus | null> {
  if (inflight?.userId === userId) return inflight.promise;
  const promise: Promise<PlanStatus | null> = getPlan()
    .then((plan) => {
      if (plan) cached = { userId, plan };
      return plan;
    })
    .catch(() => null)
    .finally(() => {
      if (inflight?.promise === promise) inflight = null;
      settledUser = userId;
      emit();
    });
  inflight = { userId, promise };
  return promise;
}

export function usePlan() {
  const { user, loading: authLoading } = useAuth();
  const userId = user?.id ?? null;
  const [, rerender] = useState(0);

  useEffect(() => {
    const l = () => rerender((n) => n + 1);
    listeners.add(l);
    return () => {
      listeners.delete(l);
    };
  }, []);

  const plan = cached && cached.userId === userId ? cached.plan : null;

  // First time we see this user: fetch. Known plans are only re-fetched on
  // an explicit refresh() so screens opening don't hammer a slow backend.
  useEffect(() => {
    if (userId && !plan) void fetchShared(userId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  const refresh = useCallback(async () => {
    if (userId) await fetchShared(userId);
  }, [userId]);

  // "Loading" until auth has settled and we either know the plan or a
  // fetch for this user has finished. No user at all is not loading.
  const loading = authLoading || (userId !== null && !plan && settledUser !== userId);

  return { plan, loading, refresh };
}
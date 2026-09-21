import { useCallback, useEffect, useState } from "react";
import { useAuth } from "./useAuth";
import { getPlan, type PlanStatus } from "../lib/billing";

export function usePlan() {
  const { user } = useAuth();
  const [plan, setPlan] = useState<PlanStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!user) {
      setPlan(null);
      setLoading(false);
      return;
    }
    const status = await getPlan();
    setPlan(status);
    setLoading(false);
  }, [user]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { plan, loading, refresh };
}
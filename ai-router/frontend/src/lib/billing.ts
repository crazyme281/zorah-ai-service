import { supabase } from "./supabase";

const BASE = import.meta.env.VITE_AI_BACKEND_URL;

export type Tier = "FREE" | "GO" | "PRO";

export interface PlanStatus {
  tier: Tier;
  role: "user" | "admin";
  subscription_status: string;
  subscription_expiration: string | null;
  grace_period_expiration: string | null;
  onboarding_completed: boolean;
  image_quota: Record<string, unknown>;
}

async function authHeader(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function getPlan(): Promise<PlanStatus | null> {
  const resp = await fetch(`${BASE}/account/plan`, { headers: await authHeader() });
  if (!resp.ok) return null;
  return resp.json();
}

/** Step 1 — reserves a tx_ref for this account before Flutterwave's
 * checkout even opens. See backend/access/payments.py for why this
 * step exists at all. */
export async function initiatePayment(tier: "GO" | "PRO") {
  const resp = await fetch(`${BASE}/payments/initiate`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeader()) },
    body: JSON.stringify({ tier }),
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => null);
    throw new Error(body?.detail || "Couldn't start checkout.");
  }
  return resp.json() as Promise<{ tx_ref: string; amount: number; currency: string; tier: string }>;
}

/** Step 2 — called once Flutterwave reports success, with its own
 * transaction id. Only the backend's independent verification against
 * Flutterwave actually grants the tier. */
export async function verifyPayment(tier: "GO" | "PRO", transactionId: string): Promise<PlanStatus> {
  const resp = await fetch(`${BASE}/payments/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeader()) },
    body: JSON.stringify({ tier, transaction_id: transactionId }),
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => null);
    throw new Error(body?.detail || "Payment verification failed.");
  }
  return resp.json();
}
/**
 * Admin > Operations - the control plane for the hosted service.
 *
 * Everything on this page is real data from GET /admin/ops/status: alerts, the
 * kill switch, per-provider circuit/budget/latency, the learned model's
 * registry (with sleep-cycle and rollback), pending human approvals and the
 * latest decision records (no message text is ever stored or shown).
 *
 * Like the rest of the admin shell, hiding the route is a courtesy: every
 * endpoint it calls re-checks role == 'admin' server-side.
 */
import { useCallback, useEffect, useState } from "react";
import { IonPage, IonContent, IonIcon, IonSpinner, useIonRouter } from "@ionic/react";
import {
  arrowBackOutline,
  refreshOutline,
  checkmarkCircleOutline,
  warningOutline,
  moonOutline,
  returnUpBackOutline,
} from "ionicons/icons";
import { TopBar } from "../components/TopBar";
import { supabase } from "../lib/supabase";
import "./adminOps.css";

const BASE = import.meta.env.VITE_AI_BACKEND_URL;

interface Alert { level: "warn" | "error"; code: string; message: string }
interface KillSwitch {
  learning_enabled: boolean;
  actions_enabled: boolean;
  forced_by_env: { learning: boolean; actions: boolean };
  reason: string;
  changed_by: string;
  changed_at: number | null;
}
interface ProviderBudget { calls: number; usd: number }
interface Budget {
  day: string;
  calls_cap_per_provider: number | null;
  usd_cap: number | null;
  estimated_usd_total: number;
  providers: Record<string, ProviderBudget>;
}
interface Circuit { state: string; consecutive_failures: number; trips: number; last_error: string }
interface ProviderMetric { calls: number; errors: number; p50_ms: number | null; p95_ms: number | null }
interface HistoryItem {
  version: string | null;
  event: string;
  at: number;
  gate: { ok: boolean; reasons: string[] } | null;
}
interface Learned {
  registry: { current: string | null; previous: string | null; pinned: boolean; history: HistoryItem[] };
  last_gate: { promoted: boolean; ok: boolean | null; reasons: string[]; at: number } | null;
  chat_learning: {
    enabled: boolean; ai_data_policy: string; storage: string; pending: number; queued: number; active: number; rejected: number;
    last_attempt: { note: string; at: number };
  };
}
interface Approval { id: string; session_id: string; action: string; summary: string; requested_at: number }
interface Decision {
  ts: number; intent: string; provider: string | null; ok: boolean; latency_ms: number; attempts: number;
}
interface Status {
  alerts: Alert[];
  killswitch: KillSwitch;
  budget: Budget;
  providers_circuit: Record<string, Circuit>;
  metrics: {
    totals: Record<string, number>;
    recent_error_rate: number;
    learned_share: number;
    providers: Record<string, ProviderMetric>;
  };
  rate_limits: { ip: { rejected_total: number }; session: { rejected_total: number } };
  emotion_memory: { sessions: number; max_sessions: number };
  learned: Learned;
  approvals_pending: Approval[];
}

async function authHeader(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function call<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    method,
    headers: { ...(await authHeader()), ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (resp.status === 403 || resp.status === 401) throw new Error("forbidden");
  if (!resp.ok) {
    const b = await resp.json().catch(() => null);
    throw new Error(b?.detail || `Request failed (${resp.status})`);
  }
  return resp.json();
}

const ago = (ts: number) => {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
};

export function AdminOpsPage() {
  const router = useIonRouter();
  const [state, setState] = useState<"loading" | "forbidden" | "ready">("loading");
  const [status, setStatus] = useState<Status | null>(null);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [reason, setReason] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [s, d] = await Promise.all([
        call<Status>("/admin/ops/status"),
        call<{ decisions: Decision[] }>("/admin/ops/decisions?limit=15"),
      ]);
      setStatus(s);
      setDecisions(d.decisions);
      setState("ready");
    } catch (e) {
      if (e instanceof Error && e.message === "forbidden") setState("forbidden");
      else {
        setError(e instanceof Error ? e.message : "Couldn't load status.");
        setState((prev) => (prev === "loading" ? "forbidden" : prev));
      }
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 20_000);
    return () => clearInterval(t);
  }, [refresh]);

  async function act(key: string, fn: () => Promise<unknown>, done?: string) {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      await fn();
      if (done) setNotice(done);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(null);
    }
  }

  const setSwitch = (which: "learning" | "actions", enabled: boolean) =>
    act(`ks-${which}`, () => call("/admin/ops/killswitch", "POST", { [which]: enabled, reason }),
      `${which === "learning" ? "Autonomous learning" : "Autonomous actions"} ${enabled ? "enabled" : "switched off"}.`);

  const runSleep = () =>
    act("sleep", async () => {
      const r = await call<{ ran: boolean; reason?: string; gate?: { promoted: boolean; reasons: string[] } }>(
        "/admin/ops/learned/sleep", "POST");
      if (!r.ran) throw new Error(r.reason || "Sleep cycle did not run.");
      setNotice(r.gate?.promoted ? "Sleep cycle finished: new version is live."
        : `Sleep cycle finished: candidate discarded (${r.gate?.reasons.join(", ") || "no change"}).`);
    });

  const rollback = () => {
    if (!window.confirm("Roll back the learned model to the previous version? It stays pinned until you unpin it.")) return;
    act("rollback", () => call("/admin/ops/learned/rollback", "POST"), "Rolled back. The previous version is live and pinned.");
  };

  const decide = (id: string, d: "approve" | "reject") =>
    act(`ap-${id}`, () => call(`/admin/ops/approvals/${id}/${d}`, "POST"), d === "approve" ? "Approved." : "Rejected.");

  return (
    <IonPage>
      <TopBar admin />
      <IonContent className="panel-page">
        <div className="ops">
          <div className="ops__top">
            <button type="button" className="ops__back" onClick={() => router.push("/admin", "back", "pop")}>
              <IonIcon icon={arrowBackOutline} /> Dashboard
            </button>
            <h2>Operations</h2>
            <button type="button" className="ops__btn" onClick={refresh} aria-label="Refresh">
              <IonIcon icon={refreshOutline} />
            </button>
          </div>

          {state === "loading" && <div className="ops__center"><IonSpinner name="crescent" /></div>}
          {state === "forbidden" && (
            <div className="ops__card"><div className="ops__row">Couldn't load operations - this account may not be an admin, or the server is unreachable.</div></div>
          )}

          {state === "ready" && status && (
            <>
              {error && <p className="ops__error">{error}</p>}
              {notice && <p className="ops__muted" style={{ marginBottom: 12 }}>{notice}</p>}

              <section className="ops__section">
                <h3>Alerts</h3>
                {status.alerts.length === 0 ? (
                  <div className="ops__ok"><IonIcon icon={checkmarkCircleOutline} /> All clear</div>
                ) : (
                  status.alerts.map((a, i) => (
                    <div key={i} className={`ops__alert ops__alert--${a.level}`}>
                      <IonIcon icon={warningOutline} /> {a.message}
                    </div>
                  ))
                )}
              </section>

              <section className="ops__section">
                <h3>Kill switch</h3>
                <div className="ops__card">
                  {(["learning", "actions"] as const).map((k) => {
                    const on = k === "learning" ? status.killswitch.learning_enabled : status.killswitch.actions_enabled;
                    const forced = status.killswitch.forced_by_env[k];
                    return (
                      <div className="ops__row" key={k}>
                        <span>
                          {k === "learning" ? "Autonomous learning" : "Autonomous actions"}
                          <small>
                            {forced ? "Forced off by the server environment" :
                              k === "learning" ? "Chat answers becoming learned knowledge, retraining, sleep cycles"
                                : "Anything the permission guard would execute"}
                          </small>
                        </span>
                        <button type="button" role="switch" aria-checked={on} className="ops__toggle"
                          disabled={busy !== null || forced} onClick={() => setSwitch(k, !on)} />
                      </div>
                    );
                  })}
                  <div className="ops__row" style={{ display: "block" }}>
                    <input className="ops__input" placeholder="Reason (kept in the audit log)" value={reason}
                      maxLength={300} onChange={(e) => setReason(e.target.value)} />
                    {status.killswitch.changed_at && (
                      <small className="ops__muted">Last change {ago(status.killswitch.changed_at)} by {status.killswitch.changed_by || "unknown"}
                        {status.killswitch.reason ? ` - "${status.killswitch.reason}"` : ""}</small>
                    )}
                  </div>
                </div>
              </section>

              <section className="ops__section">
                <h3>Providers, budget and latency</h3>
                <div className="ops__card ops__scroll">
                  <table className="ops__table">
                    <thead>
                      <tr><th>Provider</th><th>Circuit</th><th>Calls today</th><th>Est. $</th><th>p50</th><th>p95</th><th>Errors</th></tr>
                    </thead>
                    <tbody>
                      {Array.from(new Set([
                        ...Object.keys(status.budget.providers),
                        ...Object.keys(status.providers_circuit),
                        ...Object.keys(status.metrics.providers).filter((p) => p !== "none" && p !== "learned" && p !== "identity"),
                      ])).map((p) => {
                        const c = status.providers_circuit[p];
                        const m = status.metrics.providers[p];
                        const b = status.budget.providers[p];
                        const st = c?.state ?? "closed";
                        return (
                          <tr key={p}>
                            <td>{p}</td>
                            <td><span className={`ops__pill ops__pill--${st === "closed" ? "ok" : "bad"}`}>{st}</span></td>
                            <td>{b?.calls ?? 0}{status.budget.calls_cap_per_provider ? ` / ${status.budget.calls_cap_per_provider}` : ""}</td>
                            <td>{b ? b.usd.toFixed(3) : "0.000"}</td>
                            <td>{m?.p50_ms != null ? `${m.p50_ms} ms` : "-"}</td>
                            <td>{m?.p95_ms != null ? `${m.p95_ms} ms` : "-"}</td>
                            <td>{m?.errors ?? 0}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="ops__muted" style={{ marginTop: 8 }}>
                  {status.budget.usd_cap
                    ? `Spend estimate $${status.budget.estimated_usd_total.toFixed(2)} of $${status.budget.usd_cap.toFixed(2)} today (UTC ${status.budget.day}).`
                    : "No daily dollar cap set."}{" "}
                  {status.budget.calls_cap_per_provider ? "" : "No per-provider call cap set."}{" "}
                  Answered by the learned model: {Math.round(status.metrics.learned_share * 100)}% of recent requests.
                  Rate-limited so far: {status.rate_limits.ip.rejected_total + status.rate_limits.session.rejected_total}.
                  Emotion memory: {status.emotion_memory.sessions}/{status.emotion_memory.max_sessions} sessions.
                </p>
              </section>

              <section className="ops__section">
                <h3>Learned model</h3>
                <div className="ops__card">
                  <div className="ops__row">
                    <span>Live version<small>Previous: {status.learned.registry.previous ?? "none"}</small></span>
                    <span>
                      <code>{status.learned.registry.current ?? "bootstrap"}</code>{" "}
                      {status.learned.registry.pinned && <span className="ops__pill ops__pill--warn">pinned</span>}
                    </span>
                  </div>
                  {status.learned.last_gate && (
                    <div className="ops__row">
                      <span>Last evaluation gate<small>{ago(status.learned.last_gate.at)}</small></span>
                      <span className={`ops__pill ops__pill--${status.learned.last_gate.promoted ? "ok" : "bad"}`}>
                        {status.learned.last_gate.promoted ? "promoted" : `discarded: ${status.learned.last_gate.reasons.join(", ") || "no change"}`}
                      </span>
                    </div>
                  )}
                  <div className="ops__row">
                    <span>Learning from chat<small>Policy for text written by other AI models: {status.learned.chat_learning.ai_data_policy}</small></span>
                    <span className="ops__muted">
                      {status.learned.chat_learning.active} active · {status.learned.chat_learning.queued} queued · {status.learned.chat_learning.pending} pending
                    </span>
                  </div>
                  <div className="ops__row">
                    <span>Last learning attempt
                      <small>Saved in: {status.learned.chat_learning.storage === "supabase" ? "Supabase" : "local file only"}</small>
                    </span>
                    <span className="ops__muted">
                      {status.learned.chat_learning.last_attempt.at
                        ? `${status.learned.chat_learning.last_attempt.note} (${ago(status.learned.chat_learning.last_attempt.at)})`
                        : "no chat question yet"}
                    </span>
                  </div>
                  <div className="ops__actions">
                    <button type="button" className="ops__btn ops__btn--primary" disabled={busy !== null} onClick={runSleep}>
                      {busy === "sleep" ? <IonSpinner name="dots" /> : <IonIcon icon={moonOutline} />} Run sleep cycle
                    </button>
                    <button type="button" className="ops__btn ops__btn--danger" disabled={busy !== null || !status.learned.registry.previous} onClick={rollback}>
                      <IonIcon icon={returnUpBackOutline} /> Roll back
                    </button>
                    {status.learned.registry.pinned && (
                      <button type="button" className="ops__btn" disabled={busy !== null}
                        onClick={() => act("unpin", () => call("/admin/ops/learned/unpin", "POST"), "Unpinned.")}>
                        Unpin
                      </button>
                    )}
                  </div>
                </div>
              </section>

              <section className="ops__section">
                <h3>Pending approvals</h3>
                <div className="ops__card">
                  {status.approvals_pending.length === 0 && <div className="ops__row ops__muted">Nothing is waiting for a human.</div>}
                  {status.approvals_pending.map((a) => (
                    <div className="ops__row" key={a.id}>
                      <span>{a.action}<small>{a.summary || "no summary"} - requested {ago(a.requested_at)}</small></span>
                      <span style={{ display: "flex", gap: 6 }}>
                        <button type="button" className="ops__btn ops__btn--primary" disabled={busy !== null} onClick={() => decide(a.id, "approve")}>Approve</button>
                        <button type="button" className="ops__btn ops__btn--danger" disabled={busy !== null} onClick={() => decide(a.id, "reject")}>Reject</button>
                      </span>
                    </div>
                  ))}
                </div>
              </section>

              <section className="ops__section">
                <h3>Recent decisions</h3>
                <div className="ops__card ops__scroll">
                  <table className="ops__table">
                    <thead><tr><th>When</th><th>Route</th><th>Answered by</th><th>Time</th><th>Tried</th><th /></tr></thead>
                    <tbody>
                      {decisions.length === 0 && <tr><td colSpan={6} className="ops__muted">No requests yet.</td></tr>}
                      {decisions.map((d, i) => (
                        <tr key={i}>
                          <td>{ago(d.ts)}</td>
                          <td>{d.intent}</td>
                          <td>{d.provider ?? "-"}</td>
                          <td>{d.latency_ms} ms</td>
                          <td>{d.attempts}</td>
                          <td><span className={`ops__pill ops__pill--${d.ok ? "ok" : "bad"}`}>{d.ok ? "ok" : "failed"}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}
        </div>
      </IonContent>
    </IonPage>
  );
}
import { useState } from "react";
import { IonPage, IonContent, IonIcon, IonSpinner } from "@ionic/react";
import { checkmarkOutline, removeOutline, sparklesOutline } from "ionicons/icons";
import { TopBar } from "../components/TopBar";
import { useAuth } from "../hooks/useAuth";
import { usePlan } from "../hooks/usePlan";
import { initiatePayment, verifyPayment, type Tier } from "../lib/billing";
import { payWithFlutterwave } from "../lib/flutterwave";

/**
 * Feature rows are grounded in backend/access/tiers.py's real
 * ENTITLEMENTS, not the marketing copy from the pricing mockup — the
 * mockup listed "More messages" as a Go/Pro perk, but nothing in the
 * backend actually tracks or enforces a message-count limit per tier,
 * so it's left out here rather than showing a checkmark for something
 * that isn't real. Everything below IS enforced server-side.
 */
type Cell = string | boolean;
const FEATURES: { label: string; free: Cell; go: Cell; pro: Cell }[] = [
  { label: "Basic models", free: true, go: true, pro: true },
  { label: "Daily image uploads", free: "6/day", go: "10/day", pro: "15/day" },
  { label: "Faster responses", free: false, go: true, pro: true },
  { label: "AI image generation", free: false, go: false, pro: true },
  { label: "Advanced reasoning", free: false, go: false, pro: true },
  { label: "Document export (PPTX, PDF, DOCX)", free: false, go: false, pro: true },
];

const PRICES: Record<"GO" | "PRO", number> = { GO: 1500, PRO: 3000 };
const TIER_LABELS: Record<Tier, string> = { FREE: "Free", GO: "Go", PRO: "Pro" };

function Cell({ value }: { value: Cell }) {
  if (typeof value === "string") return <span className="upgrade__cell-text">{value}</span>;
  return <IonIcon icon={value ? checkmarkOutline : removeOutline} className={value ? "yes" : "no"} />;
}

export function UpgradePage() {
  const { user } = useAuth();
  const { plan, loading, refresh } = usePlan();

  // Which pair of tiers the toggle shows — defaults to the one
  // adjacent step up from the account's current tier, matching the
  // reference design (a Free account sees Free|Go; a Go account sees
  // Go|Pro — never a bare Free|Pro comparison skipping the step between).
  const currentTier = (plan?.tier ?? "FREE") as Tier;
  const pair: [Tier, Tier] = currentTier === "GO" ? ["GO", "PRO"] : ["FREE", "GO"];
  const [selected, setSelected] = useState<Tier>(pair[1]);

  const [busy, setBusy] = useState<"idle" | "initiating" | "paying" | "verifying">("idle");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  async function handlePay() {
    if (selected === "FREE" || !user?.email) return;
    const tier = selected as "GO" | "PRO";
    setError(null);
    setSuccess(false);

    try {
      setBusy("initiating");
      const { tx_ref, amount, currency } = await initiatePayment(tier);

      setBusy("paying");
      const { transactionId } = await payWithFlutterwave({
        txRef: tx_ref,
        amount,
        currency,
        email: user.email,
        title: `Zorah AI — ${TIER_LABELS[tier]}`,
      });

      setBusy("verifying");
      await verifyPayment(tier, transactionId);
      await refresh();
      setSuccess(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong with the payment.");
    } finally {
      setBusy("idle");
    }
  }

  if (loading) {
    return (
      <IonPage>
        <TopBar />
        <IonContent className="panel-page">
          <div className="upgrade__loading">
            <IonSpinner name="crescent" />
          </div>
        </IonContent>
      </IonPage>
    );
  }

  if (currentTier === "PRO") {
    return (
      <IonPage>
        <TopBar />
        <IonContent className="panel-page">
          <div className="upgrade__done">
            <IonIcon icon={sparklesOutline} />
            <h2>You&rsquo;re on Pro</h2>
            <p>You already have every feature Zorah AI offers.</p>
          </div>
        </IonContent>
      </IonPage>
    );
  }

  return (
    <IonPage>
      <TopBar />
      <IonContent className="panel-page">
        <div className="upgrade">
          <div className="upgrade__toggle">
            {pair.map((t) => (
              <button
                key={t}
                type="button"
                className={selected === t ? "active" : ""}
                onClick={() => setSelected(t)}
              >
                {TIER_LABELS[t]}
              </button>
            ))}
          </div>

          <div className="upgrade__table">
            <div className="upgrade__row upgrade__row--head">
              <span>Features</span>
              {pair.map((t) => (
                <span key={t} className={t === currentTier ? "current" : ""}>
                  {TIER_LABELS[t]}
                  {t === currentTier && <small>Current plan</small>}
                </span>
              ))}
            </div>
            {FEATURES.map((f) => (
              <div className="upgrade__row" key={f.label}>
                <span>{f.label}</span>
                <Cell value={pair[0] === "FREE" ? f.free : f.go} />
                <Cell value={pair[0] === "FREE" ? f.go : f.pro} />
              </div>
            ))}
            <div className="upgrade__row upgrade__row--price">
              <span>Price</span>
              <span>{pair[0] === "FREE" ? "Free" : `₦${PRICES.GO.toLocaleString()}/mo`}</span>
              <span>₦{PRICES[pair[1] as "GO" | "PRO"].toLocaleString()}/mo</span>
            </div>
          </div>

          {success && (
            <p className="upgrade__success">
              You&rsquo;re now on {TIER_LABELS[selected]}. Enjoy the extra room.
            </p>
          )}
          {error && <p className="upgrade__error">{error}</p>}

          {selected !== "FREE" && selected !== currentTier && !success && (
            <button type="button" className="upgrade__pay" onClick={handlePay} disabled={busy !== "idle"}>
              {busy === "idle" && `Pay Now — ₦${PRICES[selected as "GO" | "PRO"].toLocaleString()}`}
              {busy === "initiating" && <><IonSpinner name="crescent" /> Starting checkout…</>}
              {busy === "paying" && <><IonSpinner name="crescent" /> Waiting for payment…</>}
              {busy === "verifying" && <><IonSpinner name="crescent" /> Confirming…</>}
            </button>
          )}

          <p className="upgrade__note">Secure payment, powered by Flutterwave.</p>
        </div>
      </IonContent>
    </IonPage>
  );
}
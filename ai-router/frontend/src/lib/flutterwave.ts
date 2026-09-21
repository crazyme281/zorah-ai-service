/**
 * Flutterwave's inline checkout — a client-side modal widget, not a
 * redirect flow. Needs the PUBLIC key (safe to ship to the browser by
 * design, same trust model as Stripe's pk_ keys) — a different
 * credential from the SECRET key that lives only on the backend and
 * does the actual server-side verification.
 */

interface FlutterwaveCallbackResponse {
  status: string;
  transaction_id?: number;
  tx_ref: string;
}

interface FlutterwaveCheckoutOptions {
  public_key: string;
  tx_ref: string;
  amount: number;
  currency: string;
  payment_options: string;
  customer: { email: string };
  customizations: { title: string; description?: string };
  callback: (response: FlutterwaveCallbackResponse) => void;
  onclose: () => void;
}

declare global {
  interface Window {
    FlutterwaveCheckout?: (options: FlutterwaveCheckoutOptions) => void;
  }
}

const SCRIPT_URL = "https://checkout.flutterwave.com/v3.js";
let scriptPromise: Promise<void> | null = null;

function loadScript(): Promise<void> {
  if (window.FlutterwaveCheckout) return Promise.resolve();
  if (scriptPromise) return scriptPromise;

  scriptPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = SCRIPT_URL;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Couldn't load the payment provider. Check your connection."));
    document.head.appendChild(script);
  });
  return scriptPromise;
}

export async function payWithFlutterwave(opts: {
  txRef: string;
  amount: number;
  currency: string;
  email: string;
  title: string;
}): Promise<{ transactionId: string }> {
  const publicKey = import.meta.env.VITE_FLUTTERWAVE_PUBLIC_KEY;
  if (!publicKey) throw new Error("Payments aren't configured (missing Flutterwave public key).");

  await loadScript();

  return new Promise((resolve, reject) => {
    let settled = false;

    window.FlutterwaveCheckout!({
      public_key: publicKey,
      tx_ref: opts.txRef,
      amount: opts.amount,
      currency: opts.currency,
      // Lets the widget's own modal offer card, bank transfer, and USSD
      // — our UI doesn't need a separate payment-method picker, since
      // this one already covers it.
      payment_options: "card,banktransfer,ussd",
      customer: { email: opts.email },
      customizations: { title: opts.title, description: "Zorah AI subscription" },
      callback: (response) => {
        settled = true;
        if (response.status === "successful" && response.transaction_id) {
          resolve({ transactionId: String(response.transaction_id) });
        } else {
          reject(new Error("Payment wasn't completed."));
        }
      },
      onclose: () => {
        // Fires after callback too on a successful payment — the
        // reject() here is a no-op once the promise already resolved,
        // since only a settlement's first call ever takes effect.
        if (!settled) reject(new Error("Payment window closed."));
      },
    });
  });
}
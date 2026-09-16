"""
Plan upgrade payment flow via Flutterwave.

The one rule that matters: `upgrade_plan` NEVER accepts a bare
"payment succeeded" flag from the client. It only accepts a
transaction reference, looks that reference up against Flutterwave's
own verification endpoint, and only changes the user's tier if that
independent check confirms a successful charge at or above the
correct price for the tier being purchased.
"""
import requests
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from access.tiers import SubscriptionStore, Tier

# TODO: confirm the Go price with product — ₦2,000/month for Pro comes
# straight from the spec doc, but Go's price wasn't given anywhere in
# it. 1000 below is a placeholder; update before this goes live, or
# payment verification will silently accept/reject at the wrong price.
TIER_PRICES_NGN = {
    Tier.GO: 1000,
    Tier.PRO: 2000,
}

VERIFY_ENDPOINT = "https://api.flutterwave.com/v3/transactions/{tx_id}/verify"
SUBSCRIPTION_PERIOD_DAYS = 30


class PaymentVerificationError(Exception):
    pass


@dataclass
class VerifiedPayment:
    tx_id: str
    amount: float
    currency: str
    status: str


class FlutterwaveClient:
    def __init__(self, secret_key: str):
        self.secret_key = secret_key

    def verify_transaction(self, tx_id: str) -> VerifiedPayment:
        """
        Calls Flutterwave directly — the independent check. A tx_id
        the client can't forge a successful result for, because
        verification happens against Flutterwave's own record of what
        was actually charged, not anything the client asserts.
        """
        headers = {"Authorization": f"Bearer {self.secret_key}"}
        try:
            resp = requests.get(VERIFY_ENDPOINT.format(tx_id=tx_id), headers=headers, timeout=15)
        except requests.RequestException as e:
            raise PaymentVerificationError(f"could not reach Flutterwave: {e}")

        if resp.status_code >= 400:
            raise PaymentVerificationError(f"Flutterwave verify HTTP {resp.status_code}")

        data = resp.json().get("data", {})
        return VerifiedPayment(
            tx_id=str(data.get("id", tx_id)),
            amount=data.get("amount", 0),
            currency=data.get("currency", ""),
            status=data.get("status", "unknown"),
        )


def upgrade_plan(
    user_id: str,
    tx_id: str,
    tier: Tier,
    flutterwave: FlutterwaveClient,
    subscriptions: SubscriptionStore,
) -> dict:
    """
    The only legitimate path to Tier.GO or Tier.PRO. Verifies with
    Flutterwave first; only calls subscriptions.set_tier() if that
    verification confirms a successful NGN charge of at least the
    given tier's price. Returns the new subscription window.

    KNOWN GAP: this checks that the transaction was successful and
    correctly priced, but not that `tx_id` was actually initiated by
    `user_id` — Flutterwave's verify response doesn't hand that back
    unless you set metadata at payment-initiation time. Right now
    nothing stops user A from submitting user B's tx_id. Closing this
    needs a `payments` row written when the payment session is
    *started* (recording which user_id initiated which tx reference)
    and checked here before upgrading. Worth doing before this
    collects real money — flagging it rather than shipping it quietly.
    """
    if tier not in TIER_PRICES_NGN:
        raise PaymentVerificationError(f"'{tier.value}' is not a paid tier")

    payment = flutterwave.verify_transaction(tx_id)

    if payment.status.lower() != "successful":
        raise PaymentVerificationError(f"transaction {tx_id} status is '{payment.status}', not successful")
    if payment.currency.upper() != "NGN":
        raise PaymentVerificationError(f"unexpected currency '{payment.currency}'")
    if payment.amount < TIER_PRICES_NGN[tier]:
        raise PaymentVerificationError(
            f"transaction {tx_id} amount {payment.amount} is below the {tier.value} price of {TIER_PRICES_NGN[tier]}"
        )

    start = datetime.now(timezone.utc)
    expiration = start + timedelta(days=SUBSCRIPTION_PERIOD_DAYS)
    subscriptions.set_tier(user_id, tier, start, expiration)
    return {
        "tier": tier.value,
        "subscription_start": start.isoformat(),
        "subscription_expiration": expiration.isoformat(),
    }
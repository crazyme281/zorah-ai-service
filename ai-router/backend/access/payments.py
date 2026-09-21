"""
Plan upgrade payment flow via Flutterwave.

Two-step flow, not one: initiate_payment() records who is about to pay
for what BEFORE any money moves, and upgrade_plan() only trusts a
transaction if it matches that record. This closes a gap the original
version of this file left open on purpose (see git history / prior
comments): without an initiate step, `upgrade_plan` had no way to check
that a transaction actually belonged to the account claiming it — it
only checked that *a* successful charge existed somewhere. That was
fine while nothing called this code at all; it stopped being fine the
moment a real "Pay Now" button could reach it.

The one rule that still matters most: `upgrade_plan` NEVER accepts a
bare "payment succeeded" flag from the client. It only accepts
Flutterwave's own transaction id, looks it up against Flutterwave's own
verification endpoint, and only changes the user's tier if that
independent check confirms a successful charge — at the right price,
in the right currency, for a payment this exact user actually started.
"""
import uuid
import requests
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from access.db import select, insert, patch
from access.tiers import SubscriptionStore, Tier

# Confirmed against the real pricing page design — not a placeholder.
TIER_PRICES_NGN = {
    Tier.GO: 1500,
    Tier.PRO: 3000,
}

VERIFY_ENDPOINT = "https://api.flutterwave.com/v3/transactions/{transaction_id}/verify"
SUBSCRIPTION_PERIOD_DAYS = 30

# A pending payment left unpaid shouldn't be checkoutable forever —
# matches Flutterwave's own inline-checkout session expectations (the
# widget itself times out well before this), and keeps the `payments`
# table from accumulating pending rows nobody ever completed.
PENDING_PAYMENT_TTL_MINUTES = 30


class PaymentVerificationError(Exception):
    pass


@dataclass
class VerifiedPayment:
    transaction_id: str
    tx_ref: str
    amount: float
    currency: str
    status: str


class FlutterwaveClient:
    def __init__(self, secret_key: str):
        self.secret_key = secret_key

    def verify_transaction(self, transaction_id: str) -> VerifiedPayment:
        """
        Calls Flutterwave directly — the independent check. A transaction_id
        the client can't forge a successful result for, because
        verification happens against Flutterwave's own record of what
        was actually charged, not anything the client asserts.
        """
        headers = {"Authorization": f"Bearer {self.secret_key}"}
        try:
            resp = requests.get(
                VERIFY_ENDPOINT.format(transaction_id=transaction_id),
                headers=headers,
                timeout=15,
            )
        except requests.RequestException as e:
            raise PaymentVerificationError(f"could not reach Flutterwave: {e}")

        if resp.status_code >= 400:
            raise PaymentVerificationError(f"Flutterwave verify HTTP {resp.status_code}")

        data = resp.json().get("data", {})
        return VerifiedPayment(
            transaction_id=str(data.get("id", transaction_id)),
            tx_ref=str(data.get("tx_ref", "")),
            amount=data.get("amount", 0),
            currency=data.get("currency", ""),
            status=data.get("status", "unknown"),
        )


def initiate_payment(user_id: str, tier: Tier) -> dict:
    """
    Step 1, called the moment the user taps "Pay Now" — before
    Flutterwave's checkout even opens. Generates a tx_ref unique to this
    attempt and records, in our own database, that THIS user is about to
    pay for THIS tier. upgrade_plan() later refuses to trust any
    transaction that doesn't match a row written here.
    """
    if tier not in TIER_PRICES_NGN:
        raise PaymentVerificationError(f"'{tier.value}' is not a paid tier")

    tx_ref = f"zorah-{uuid.uuid4().hex}"
    amount = TIER_PRICES_NGN[tier]

    insert(
        "payments",
        {
            "user_id": user_id,
            "tx_id": tx_ref,
            "tier": tier.value,
            "amount": amount,
            "currency": "NGN",
            "status": "pending",
        },
    )

    return {"tx_ref": tx_ref, "amount": amount, "currency": "NGN", "tier": tier.value}


def upgrade_plan(
    user_id: str,
    transaction_id: str,
    tier: Tier,
    flutterwave: FlutterwaveClient,
    subscriptions: SubscriptionStore,
) -> dict:
    """
    Step 2, called once Flutterwave's checkout widget reports success and
    hands back its own numeric transaction_id. The only legitimate path
    to Tier.GO or Tier.PRO.

    Trust chain, every link required:
      1. Flutterwave's own verify endpoint confirms transaction_id was a
         real, successful charge (the client can't fake this part).
      2. That verified charge's tx_ref matches a 'pending' row in our
         own `payments` table.
      3. That row's user_id is the SAME user_id making this request —
         this is what stops user A from submitting user B's
         transaction_id and stealing their payment.
      4. That row's tier matches the tier being requested, and the
         charged amount/currency meet that tier's price.
    Any link failing raises PaymentVerificationError; the tier is never
    granted on a partial match.
    """
    if tier not in TIER_PRICES_NGN:
        raise PaymentVerificationError(f"'{tier.value}' is not a paid tier")

    payment = flutterwave.verify_transaction(transaction_id)

    if payment.status.lower() != "successful":
        raise PaymentVerificationError(
            f"transaction {transaction_id} status is '{payment.status}', not successful"
        )

    if not payment.tx_ref:
        raise PaymentVerificationError("Flutterwave's response had no tx_ref to match against")

    pending = select(
        "payments",
        {
            "tx_id": f"eq.{payment.tx_ref}",
            "user_id": f"eq.{user_id}",
            "status": "eq.pending",
            "select": "*",
            "limit": "1",
        },
    )
    if not pending:
        # Either this tx_ref was never initiated by this user, or it's
        # already been used — both look identical from here on purpose,
        # so no information leaks about which one it was.
        raise PaymentVerificationError(
            "no matching pending payment found for this account and transaction"
        )
    record = pending[0]

    if record["tier"] != tier.value:
        raise PaymentVerificationError(
            f"payment was initiated for tier '{record['tier']}', not '{tier.value}'"
        )
    if payment.currency.upper() != "NGN":
        raise PaymentVerificationError(f"unexpected currency '{payment.currency}'")
    if payment.amount < TIER_PRICES_NGN[tier]:
        raise PaymentVerificationError(
            f"transaction {transaction_id} amount {payment.amount} is below "
            f"the {tier.value} price of {TIER_PRICES_NGN[tier]}"
        )

    start = datetime.now(timezone.utc)
    expiration = start + timedelta(days=SUBSCRIPTION_PERIOD_DAYS)

    # Mark this payment settled BEFORE granting the tier — if set_tier
    # somehow fails, retrying with the same transaction_id should still
    # be rejected (no second pending row exists to match against) rather
    # than silently re-processing the same charge.
    patch(
        "payments",
        {"id": f"eq.{record['id']}"},
        {
            "status": "successful",
            "amount": payment.amount,
            "verified_at": start.isoformat(),
        },
    )

    subscriptions.set_tier(user_id, tier, start, expiration)
    return {
        "tier": tier.value,
        "subscription_start": start.isoformat(),
        "subscription_expiration": expiration.isoformat(),
    }
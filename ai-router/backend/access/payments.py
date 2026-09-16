"""
Pro upgrade payment flow via Flutterwave.

The one rule that matters: `upgrade_to_pro` NEVER accepts a bare
"payment succeeded" flag from the client. It only accepts a
transaction reference, looks that reference up against Flutterwave's
own verification endpoint, and only flips the user to PRO if that
independent check confirms a successful, correctly-priced charge.
"""
import requests
from dataclasses import dataclass

from access.tiers import SubscriptionStore, Tier

PRO_PRICE_NGN = 3000
VERIFY_ENDPOINT = "https://api.flutterwave.com/v3/transactions/{tx_id}/verify"


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
        Calls Flutterwave directly — this is the independent check.
        A tx_id the client can't forge a successful result for, because
        the verification happens against Flutterwave's own record of
        what was actually charged, not anything the client asserts.
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


def upgrade_to_pro(
    user_id: str,
    tx_id: str,
    flutterwave: FlutterwaveClient,
    subscriptions: SubscriptionStore,
) -> bool:
    """
    The only legitimate path to Tier.PRO. Verifies with Flutterwave
    first; only calls subscriptions.set_tier() if that verification
    confirms a successful charge of at least PRO_PRICE_NGN in NGN.
    Returns True on success, raises PaymentVerificationError otherwise.
    """
    payment = flutterwave.verify_transaction(tx_id)

    if payment.status.lower() != "successful":
        raise PaymentVerificationError(f"transaction {tx_id} status is '{payment.status}', not successful")
    if payment.currency.upper() != "NGN":
        raise PaymentVerificationError(f"unexpected currency '{payment.currency}'")
    if payment.amount < PRO_PRICE_NGN:
        raise PaymentVerificationError(
            f"transaction {tx_id} amount {payment.amount} is below the Pro price of {PRO_PRICE_NGN}"
        )

    subscriptions.set_tier(user_id, Tier.PRO)
    return True

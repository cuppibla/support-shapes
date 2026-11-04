"""Fake store for the support demo. Deterministic on purpose: every run of the
screencast sees the same orders, the same carrier answers, the same amounts.

Scenarios (keyed by order number):
  4821  lost in transit, $42      → the main path: refund
  4822  still in transit          → no refund, give the ETA
  4823  lost in transit, $650     → over the auto-refund limit → human review
  4824  belongs to another customer → not found for the signed-in customer
  (no number in the message)      → ask the customer
"""

SIGNED_IN_CUSTOMER = "cust_001"

AUTO_REFUND_LIMIT = 500.00          # above this, a person has to approve
REFUNDABLE_STATUSES = {"lost", "damaged"}

ORDERS = {
    "4821": {"order_id": "4821", "customer_id": "cust_001", "item": "Noise-cancelling headphones",
             "amount": 42.00, "tracking_number": "TRK-4821", "paid": True},
    "4822": {"order_id": "4822", "customer_id": "cust_001", "item": "Desk lamp",
             "amount": 29.00, "tracking_number": "TRK-4822", "paid": True},
    "4823": {"order_id": "4823", "customer_id": "cust_001", "item": "Espresso machine",
             "amount": 650.00, "tracking_number": "TRK-4823", "paid": True},
    "4824": {"order_id": "4824", "customer_id": "cust_002", "item": "Running shoes",
             "amount": 120.00, "tracking_number": "TRK-4824", "paid": True},
}

TRACKING = {
    "TRK-4821": {"status": "lost", "detail": "Carrier confirmed the package was lost in transit on Oct 2."},
    "TRK-4822": {"status": "in_transit", "detail": "Left the regional hub this morning.", "eta": "Oct 10"},
    "TRK-4823": {"status": "lost", "detail": "Carrier confirmed the package was lost in transit on Oct 4."},
    "TRK-4824": {"status": "delivered", "detail": "Delivered Sep 30, signed by resident."},
}

# Refunds issued so far, by order id. Mutated by issue_refund() / request_refund().
REFUNDS: dict[str, dict] = {}


def reset() -> None:
    """Forget issued refunds. Every root run calls this first, so the same order can
    be replayed across all three apps on camera. (A real store would persist.)"""
    REFUNDS.clear()


def eligibility_token(order_id: str, status: str) -> str:
    """The token refund_policy() hands out and request_refund() demands back.
    It is how the code — not the model — guarantees the policy step happened."""
    return f"ELIG-{order_id}-{status}"

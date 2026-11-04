"""The tools. Plain functions — ADK turns them into FunctionTools from the
signature and docstring. The same four are reused by every architecture."""

from __future__ import annotations

from . import data


def look_up_order(order_id: str) -> dict:
    """Look up an order by its order number for the signed-in customer.

    Args:
        order_id: The order number, e.g. "4821".
    Returns:
        The order (item, amount, tracking_number) or an error if not found.
    """
    order = data.ORDERS.get(order_id.strip().lstrip("#"))
    if not order or order["customer_id"] != data.SIGNED_IN_CUSTOMER:
        return {"found": False, "error": f"No order {order_id} for the signed-in customer."}
    return {"found": True, **order}


def check_tracking(tracking_number: str) -> dict:
    """Check the carrier's delivery status for a tracking number.

    Args:
        tracking_number: e.g. "TRK-4821".
    Returns:
        status: one of lost / in_transit / delivered, plus carrier detail and eta.
    """
    info = data.TRACKING.get(tracking_number.strip())
    if not info:
        return {"status": "unknown", "detail": f"Carrier has no record of {tracking_number}."}
    return {"tracking_number": tracking_number, **info}


def payment_lookup(order_id: str) -> dict:
    """Look up the payment and refund history for an order.

    Args:
        order_id: The order number.
    Returns:
        amount paid and any refund already issued.
    """
    order = data.ORDERS.get(order_id.strip().lstrip("#"))
    if not order:
        return {"found": False, "error": f"No payment record for order {order_id}."}
    return {
        "found": True,
        "order_id": order["order_id"],
        "amount_paid": order["amount"],
        "already_refunded": data.REFUNDS.get(order["order_id"], {}).get("amount", 0.0),
    }


def refund_policy(order_id: str, delivery_status: str) -> dict:
    """Check whether an order is eligible for a refund under the refund policy.

    Args:
        order_id: The order number.
        delivery_status: The carrier status from check_tracking (lost / in_transit / delivered).
    Returns:
        eligible, the refundable amount, whether a human must approve it, and —
        when eligible — an eligibility_token that request_refund requires.
    """
    order = data.ORDERS.get(order_id.strip().lstrip("#"))
    if not order:
        return {"eligible": False, "reason": f"Order {order_id} not found."}
    status = delivery_status.strip().lower()
    if status not in data.REFUNDABLE_STATUSES:
        return {"eligible": False,
                "reason": f"Status '{status}' is not refundable. Refunds apply to: "
                          f"{sorted(data.REFUNDABLE_STATUSES)}."}
    already = data.REFUNDS.get(order["order_id"], {}).get("amount", 0.0)
    refundable = round(order["amount"] - already, 2)
    if refundable <= 0:
        return {"eligible": False, "reason": "This order has already been refunded in full."}
    return {
        "eligible": True,
        "refundable_amount": refundable,
        "needs_human_review": refundable > data.AUTO_REFUND_LIMIT,
        "auto_refund_limit": data.AUTO_REFUND_LIMIT,
        "eligibility_token": data.eligibility_token(order["order_id"], status),
    }


def request_refund(order_id: str, eligibility_token: str) -> dict:
    """Request a refund for an order. Requires the eligibility_token from refund_policy.

    The code behind this tool checks that the refund is allowed before it moves
    money: a valid token, no duplicate refund, and the amount within the
    auto-refund limit.

    Args:
        order_id: The order number.
        eligibility_token: The token returned by refund_policy.
    Returns:
        The refund result, or a refusal with the reason.
    """
    order = data.ORDERS.get(order_id.strip().lstrip("#"))
    if not order:
        return {"refunded": False, "reason": f"Order {order_id} not found."}
    oid = order["order_id"]
    status = eligibility_token.replace(f"ELIG-{oid}-", "", 1) if eligibility_token else ""
    if eligibility_token != data.eligibility_token(oid, status) or status not in data.REFUNDABLE_STATUSES:
        return {"refunded": False, "reason": "Invalid eligibility token — call refund_policy first."}
    if oid in data.REFUNDS:
        return {"refunded": False, "reason": f"Order {oid} was already refunded (${data.REFUNDS[oid]['amount']:.2f})."}
    if order["amount"] > data.AUTO_REFUND_LIMIT:
        return {"refunded": False, "needs_human_review": True,
                "reason": f"${order['amount']:.2f} exceeds the ${data.AUTO_REFUND_LIMIT:.0f} auto-refund limit; "
                          "a support manager has to approve this one."}
    data.REFUNDS[oid] = {"amount": order["amount"], "payment_ref": f"PAY-REF-{oid}"}
    return {"refunded": True, "amount": order["amount"], "payment_ref": f"PAY-REF-{oid}"}

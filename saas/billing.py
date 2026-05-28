"""Stripe billing — Checkout sessions and subscription verification."""
import os


def _stripe():
    import stripe
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    return stripe


def create_checkout_url(user_id: str, email: str, tier: str) -> str:
    """
    Create a Stripe Checkout Session and return the hosted URL.
    Returns '' if Stripe is not configured or price IDs are missing.
    """
    if not os.environ.get("STRIPE_SECRET_KEY"):
        return ""

    price_ids = {
        "pro":     os.environ.get("STRIPE_PRICE_PRO", ""),
        "premium": os.environ.get("STRIPE_PRICE_PREMIUM", ""),
    }
    price_id = price_ids.get(tier, "")
    if not price_id:
        return ""

    try:
        s       = _stripe()
        app_url = os.environ.get("APP_URL", "http://localhost:8501")
        session = s.checkout.Session.create(
            customer_email=email,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{app_url}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{app_url}?payment=cancelled",
            metadata={"user_id": user_id},
            allow_promotion_codes=True,
        )
        return session.url or ""
    except Exception:
        return ""


def verify_and_activate(session_id: str, user_id: str) -> str:
    """
    Verify a completed Stripe Checkout session.
    Activates the subscription in Supabase and returns the tier ('pro'/'premium').
    Returns '' if verification fails.
    """
    if not os.environ.get("STRIPE_SECRET_KEY"):
        return ""

    try:
        s       = _stripe()
        session = s.checkout.Session.retrieve(session_id)

        if session.get("payment_status") != "paid":
            return ""
        if session.get("metadata", {}).get("user_id") != user_id:
            return ""

        line_items  = s.checkout.Session.list_line_items(session_id)
        bought_price = line_items.data[0].price.id if line_items.data else ""

        tier = "free"
        if bought_price == os.environ.get("STRIPE_PRICE_PREMIUM"):
            tier = "premium"
        elif bought_price == os.environ.get("STRIPE_PRICE_PRO"):
            tier = "pro"

        if tier != "free":
            customer_id = session.get("customer", "")
            from saas.db import set_subscription_tier
            set_subscription_tier(user_id, tier, customer_id)

        return tier
    except Exception:
        return ""


def get_customer_portal_url(stripe_customer_id: str) -> str:
    """Return a Stripe Customer Portal URL so users can manage their subscription."""
    try:
        s       = _stripe()
        app_url = os.environ.get("APP_URL", "http://localhost:8501")
        portal  = s.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=app_url,
        )
        return portal.url or ""
    except Exception:
        return ""

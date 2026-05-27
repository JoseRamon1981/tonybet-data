"""Supabase database operations (per-user bet tracking)."""
import os
from datetime import date, timedelta


def _get_supabase():
    from supabase import create_client
    # Use service key for server-side ops; fall back to anon key
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_ANON_KEY"]
    return create_client(os.environ["SUPABASE_URL"], key)


def get_user_profile(user_id: str) -> dict:
    """Return user row; defaults if not found."""
    supabase = _get_supabase()
    result   = supabase.table("users").select("*").eq("id", user_id).execute()
    return result.data[0] if result.data else {
        "subscription_tier": "free",
        "bankroll":          200.0,
        "kelly_fraction":    0.25,
    }


def set_subscription_tier(user_id: str, tier: str, stripe_customer_id: str = "") -> None:
    """Activate a paid subscription tier."""
    supabase = _get_supabase()
    update   = {"subscription_tier": tier}
    if stripe_customer_id:
        update["stripe_customer_id"] = stripe_customer_id
    supabase.table("users").update(update).eq("id", user_id).execute()


def save_user_bets(user_id: str, bets: list[dict]) -> int:
    """
    Upsert today's recommended bets into the user's history.
    Returns number of records written.
    """
    supabase = _get_supabase()
    today    = str(date.today())

    records = [
        {
            "user_id":      user_id,
            "date":         today,
            "event":        b.get("event", ""),
            "sport":        b.get("sport", ""),
            "market":       b.get("market", ""),
            "selection":    b.get("selection", ""),
            "odds":         b.get("odds", 0),
            "stake":        b.get("recommended_stake", 0),
            "estimated_ev": b.get("expected_value", 0),
            "result":       "pending",
            "profit":       0.0,
        }
        for b in bets
    ]

    if records:
        supabase.table("bets").upsert(
            records,
            on_conflict="user_id,event,selection,date",
        ).execute()

    return len(records)


def get_user_bets(user_id: str, days: int = 30) -> list[dict]:
    """Return user's bet history for the last N days, newest first."""
    supabase = _get_supabase()
    since    = str(date.today() - timedelta(days=days))
    result   = (
        supabase.table("bets")
        .select("*")
        .eq("user_id", user_id)
        .gte("date", since)
        .order("date", desc=True)
        .execute()
    )
    return result.data or []


def update_bet_result(user_id: str, bet_id: str, result_val: str) -> None:
    """Mark a bet as won / lost / void and calculate profit."""
    supabase   = _get_supabase()
    bet_result = (
        supabase.table("bets")
        .select("odds, stake")
        .eq("id", bet_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not bet_result.data:
        return

    bet = bet_result.data[0]
    if result_val == "won":
        profit = bet["stake"] * (bet["odds"] - 1)
    elif result_val == "lost":
        profit = -bet["stake"]
    else:
        profit = 0.0

    supabase.table("bets").update({
        "result": result_val,
        "profit": profit,
    }).eq("id", bet_id).eq("user_id", user_id).execute()

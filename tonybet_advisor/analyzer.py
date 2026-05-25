"""
Value betting calculations: Expected Value, Kelly Criterion, overround.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class BetAnalysis:
    event: str
    sport: str
    market: str
    selection: str
    odds: float
    implied_probability: float
    estimated_probability: float
    expected_value: float
    kelly_fraction: float
    recommended_stake: float
    is_value_bet: bool
    overround: float
    starts_at: str = ""


def implied_prob(odds: float) -> float:
    """Convert decimal odds to implied probability."""
    return 1.0 / odds if odds > 0 else 0.0


def expected_value(odds: float, prob_win: float) -> float:
    """
    EV = (prob_win * net_profit) - (prob_lose * stake)
    Normalised to stake=1, so EV > 0 means profitable.
    """
    prob_lose = 1.0 - prob_win
    net_profit = odds - 1.0
    return (prob_win * net_profit) - prob_lose


def kelly_criterion(odds: float, prob_win: float) -> float:
    """
    Kelly fraction = (b*p - q) / b
    b = net odds (decimal - 1), p = prob_win, q = prob_lose
    Returns 0 if negative (no bet).
    """
    b = odds - 1.0
    p = prob_win
    q = 1.0 - p
    if b <= 0:
        return 0.0
    fraction = (b * p - q) / b
    return max(0.0, fraction)


def overround(odds_list: list[float]) -> float:
    """Bookmaker margin: sum of implied probs - 1. Higher = worse for bettor."""
    return sum(implied_prob(o) for o in odds_list) - 1.0


def analyse_bet(
    event: str,
    sport: str,
    market: str,
    selection: str,
    odds: float,
    market_odds: list[float],
    estimated_prob: Optional[float],
    bankroll: float,
    kelly_fraction: float = 0.25,
    min_ev: float = 0.03,
    max_stake: float = 10.0,
    starts_at: str = "",
) -> BetAnalysis:
    """
    Full analysis of a single bet selection.
    `estimated_prob` comes from Claude's assessment; if None we use fair odds.
    """
    imp = implied_prob(odds)
    over = overround(market_odds)

    # If no external probability estimate, use fair odds (remove margin)
    if estimated_prob is None:
        total_imp = sum(implied_prob(o) for o in market_odds)
        estimated_prob = imp / total_imp if total_imp > 0 else imp

    ev = expected_value(odds, estimated_prob)
    raw_kelly = kelly_criterion(odds, estimated_prob)
    fractional_kelly = raw_kelly * kelly_fraction
    stake = min(bankroll * fractional_kelly, max_stake)
    stake = round(max(0.0, stake), 2)

    return BetAnalysis(
        event=event,
        sport=sport,
        market=market,
        selection=selection,
        odds=odds,
        implied_probability=round(imp, 4),
        estimated_probability=round(estimated_prob, 4),
        expected_value=round(ev, 4),
        kelly_fraction=round(fractional_kelly, 4),
        recommended_stake=stake,
        is_value_bet=ev >= min_ev and stake > 0,
        overround=round(over, 4),
        starts_at=starts_at,
    )

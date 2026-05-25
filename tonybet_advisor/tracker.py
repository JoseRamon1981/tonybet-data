"""
Daily P&L tracker: records every bet placed and calculates running stats.
Saves to bets_log.json in the project directory.
"""
import json
import os
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path

from .analyzer import BetAnalysis

LOG_FILE  = Path(__file__).parent.parent / "bets_log.json"
RECS_FILE = Path(__file__).parent.parent / "recommendations_latest.json"


@dataclass
class BetRecord:
    date: str
    event: str
    sport: str
    market: str
    selection: str
    odds: float
    stake: float
    estimated_ev: float
    result: str        # "pending" | "won" | "lost" | "void"
    profit: float = 0.0


def _load() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(records: list[dict]):
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def save_latest_recommendations(bets: list[BetAnalysis]) -> None:
    """Save current recommendations to JSON for the web dashboard."""
    data = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "bets": [
            {
                "event": b.event,
                "sport": b.sport,
                "market": b.market,
                "selection": b.selection,
                "odds": b.odds,
                "expected_value": b.expected_value,
                "recommended_stake": b.recommended_stake,
                "estimated_probability": b.estimated_probability,
            }
            for b in bets
        ],
    }
    with open(RECS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def record_bets(bets: list[BetAnalysis]) -> None:
    records = _load()
    today = date.today().isoformat()
    for b in bets:
        records.append(asdict(BetRecord(
            date=today,
            event=b.event,
            sport=b.sport,
            market=b.market,
            selection=b.selection,
            odds=b.odds,
            stake=b.recommended_stake,
            estimated_ev=b.expected_value,
            result="pending",
        )))
    _save(records)
    print(f"  ✓ {len(bets)} apuesta(s) registrada(s) en bets_log.json")


def update_result(event: str, selection: str, result: str) -> None:
    """Mark a pending bet as won/lost/void and calculate profit."""
    records = _load()
    updated = 0
    for r in records:
        if r["event"] == event and r["selection"] == selection and r["result"] == "pending":
            r["result"] = result
            if result == "won":
                r["profit"] = round(r["stake"] * (r["odds"] - 1), 2)
            elif result == "lost":
                r["profit"] = -r["stake"]
            elif result == "void":
                r["profit"] = 0.0
            updated += 1
    _save(records)
    print(f"  ✓ {updated} apuesta(s) actualizadas como '{result}'")


def print_stats(days: int = 30) -> None:
    records = _load()
    if not records:
        print("Sin historial de apuestas todavía.")
        return

    from datetime import timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    recent = [r for r in records if r["date"] >= cutoff]
    settled = [r for r in recent if r["result"] in ("won", "lost", "void")]
    pending = [r for r in recent if r["result"] == "pending"]

    if not settled:
        print(f"Sin apuestas liquidadas en los últimos {days} días.")
        if pending:
            print(f"  Pendientes: {len(pending)}")
        return

    total_stake = sum(r["stake"] for r in settled)
    total_profit = sum(r["profit"] for r in settled)
    won = sum(1 for r in settled if r["result"] == "won")
    lost = sum(1 for r in settled if r["result"] == "lost")
    roi = (total_profit / total_stake * 100) if total_stake > 0 else 0

    # Daily breakdown
    by_day: dict[str, float] = {}
    for r in settled:
        by_day[r["date"]] = by_day.get(r["date"], 0) + r["profit"]

    print(f"\n{'='*50}")
    print(f"  ESTADÍSTICAS — últimos {days} días")
    print(f"{'='*50}")
    print(f"  Apuestas liquidadas : {len(settled)}  (ganadas {won} / perdidas {lost})")
    print(f"  Tasa de acierto     : {won/len(settled)*100:.1f}%")
    print(f"  Stake total         : {total_stake:.2f}€")
    print(f"  Beneficio total     : {total_profit:+.2f}€")
    print(f"  ROI                 : {roi:+.1f}%")
    print(f"  Promedio diario     : {total_profit/max(len(by_day),1):+.2f}€/día")
    print(f"  Pendientes          : {len(pending)}")
    print(f"\n  Resultados por día:")
    for d in sorted(by_day)[-10:]:
        bar = "█" * int(abs(by_day[d])) if abs(by_day[d]) < 40 else "█" * 40
        sign = "+" if by_day[d] >= 0 else "-"
        print(f"    {d}  {sign}{abs(by_day[d]):.2f}€  {bar}")
    print()

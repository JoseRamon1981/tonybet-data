"""
Comprehensive team/player context fetcher using ESPN's unofficial API.

Provides per-team:
  - Full season record: position, points, W/D/L, GF/GA, home/away splits
  - Over/Under and BTTS rates calculated from the full schedule
  - Scoring trends: last-10 vs season average
  - Clean-sheet % and fail-to-score %
  - Advanced stats where ESPN has them (shots, possession, xG, pace, etc.)
  - Last-10 results with scorelines
  - H2H (last 5 direct meetings)
  - Injuries

For tennis: ATP/WTA ranking + surface stats + recent results.
No API key required.
"""
from __future__ import annotations

import re
import requests
from difflib import SequenceMatcher
from dataclasses import dataclass, field

_H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}
_S = requests.Session()
_S.headers.update(_H)
_T = 8  # timeout seconds

# ── ESPN league map ───────────────────────────────────────────────────────────
_LEAGUES: dict[str, list[tuple[str, str]]] = {
    "Futbol": [
        ("soccer", "eng.1"),
        ("soccer", "esp.1"),
        ("soccer", "ger.1"),
        ("soccer", "ita.1"),
        ("soccer", "fra.1"),
        ("soccer", "ned.1"),
        ("soccer", "por.1"),
        ("soccer", "tur.1"),
        ("soccer", "mex.1"),
        ("soccer", "usa.1"),
        ("soccer", "bra.1"),
        ("soccer", "arg.1"),
        ("soccer", "esp.2"),
        ("soccer", "eng.2"),
        ("soccer", "uefa.champions"),
        ("soccer", "uefa.europa"),
    ],
    "Baloncesto": [
        ("basketball", "nba"),
        ("basketball", "mens-college-basketball"),
        ("basketball", "euroleague"),
    ],
    "Hockey hielo": [
        ("hockey", "nhl"),
    ],
    "Béisbol": [("baseball", "mlb")],
    "Futbol americano": [("football", "nfl"), ("football", "college-football")],
    "Rugby": [("rugby", "premiership"), ("rugby", "superrugby")],
}

# ── caches ────────────────────────────────────────────────────────────────────
_team_index:    dict[str, tuple[str, str, str]] = {}
_indexed_sports: set[str] = set()
_record_cache:   dict[tuple, dict] = {}
_schedule_cache: dict[tuple, list] = {}
_stats_cache:    dict[tuple, dict] = {}

_tennis_players:      dict[str, dict] = {}
_tennis_tours_built:  set[str] = set()


# ── helpers ───────────────────────────────────────────────────────────────────

def _get(url: str, params: dict | None = None) -> dict:
    try:
        r = _S.get(url, params=params, timeout=_T)
        return r.json() if r.ok else {}
    except Exception:
        return {}


def _score_str(val) -> str:
    if isinstance(val, dict):
        return val.get("displayValue", "?")
    if val is not None:
        v = float(val)
        return str(int(v)) if v == int(v) else str(v)
    return "?"


def _clean_name(name: str) -> str:
    return re.sub(
        r"\b(fc|sc|ac|bc|cf|sv|bv|vfl|tsg|rb|ss|as|us|sd|ud|rc|gd|fk|sk|nk|hk|hc|bk|if|afc|united|city|hotspur)\b",
        "", name.lower(), flags=re.I
    ).strip()


def _int(val, default: int = 0) -> int:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def _float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _pct(num: int, den: int, decimals: int = 1) -> str:
    if den == 0:
        return "?"
    return f"{round(100 * num / den, decimals)}%"


# ── team index ────────────────────────────────────────────────────────────────

def _build_index(sport_name: str) -> None:
    if sport_name in _indexed_sports:
        return
    _indexed_sports.add(sport_name)
    for sport_slug, league_slug in _LEAGUES.get(sport_name, []):
        data = _get(
            f"https://site.api.espn.com/apis/site/v2/sports/{sport_slug}/{league_slug}/teams"
        )
        raw = (data.get("sports") or [{}])[0].get("leagues", [{}])[0].get("teams", [])
        for entry in raw:
            t   = entry.get("team", {})
            tid = str(t.get("id", ""))
            for key in ["displayName", "name", "shortDisplayName", "abbreviation"]:
                val = (t.get(key) or "").lower()
                if val and val not in _team_index:
                    _team_index[val] = (sport_slug, league_slug, tid)


def _find_team(name: str, sport_name: str) -> tuple[str, str, str] | None:
    _build_index(sport_name)
    name_l = name.lower().strip()
    if name_l in _team_index:
        return _team_index[name_l]
    cleaned = _clean_name(name)
    if cleaned and cleaned in _team_index:
        return _team_index[cleaned]
    best, best_r = None, 0.0
    for key, val in _team_index.items():
        r = SequenceMatcher(None, name_l, key).ratio()
        if r > best_r:
            best_r, best = r, val
    return best if best_r >= 0.72 else None


# ── season record ─────────────────────────────────────────────────────────────

def _team_record(sport_slug: str, league_slug: str, team_id: str) -> dict:
    key = (sport_slug, league_slug, team_id)
    if key in _record_cache:
        return _record_cache[key]

    data = _get(
        f"https://site.api.espn.com/apis/site/v2/sports/{sport_slug}/{league_slug}/teams/{team_id}"
    )
    team  = data.get("team", {})
    items = team.get("record", {}).get("items", [])

    if not items:
        _record_cache[key] = {}
        return {}

    total = next((i for i in items if i.get("type") == "total"), items[0])
    stats = {s["name"]: s.get("value", 0) for s in total.get("stats", [])}

    result = {
        "position": _int(stats.get("rank", 0)) or "?",
        "points":   _int(stats.get("points", 0)),
        "played":   _int(stats.get("gamesPlayed", 0)),
        "won":      _int(stats.get("wins", 0)),
        "drawn":    _int(stats.get("ties", 0)),
        "lost":     _int(stats.get("losses", 0)),
        "gf":       _int(stats.get("pointsFor", 0)),
        "ga":       _int(stats.get("pointsAgainst", 0)),
        "home_played": _int(stats.get("homeGamesPlayed", 0)),
        "home_won":    _int(stats.get("homeWins", 0)),
        "home_drawn":  _int(stats.get("homeTies", 0)),
        "home_lost":   _int(stats.get("homeLosses", 0)),
        "home_gf":     _int(stats.get("homePointsFor", 0)),
        "home_ga":     _int(stats.get("homePointsAgainst", 0)),
        "away_played": _int(stats.get("awayGamesPlayed", 0)),
        "away_won":    _int(stats.get("awayWins", 0)),
        "away_drawn":  _int(stats.get("awayTies", 0)),
        "away_lost":   _int(stats.get("awayLosses", 0)),
        "away_gf":     _int(stats.get("awayPointsFor", 0)),
        "away_ga":     _int(stats.get("awayPointsAgainst", 0)),
    }
    _record_cache[key] = result
    return result


# ── advanced team statistics ──────────────────────────────────────────────────

def _team_statistics(sport_slug: str, league_slug: str, team_id: str) -> dict:
    """Fetch advanced stats from ESPN statistics endpoint."""
    key = (sport_slug, league_slug, team_id)
    if key in _stats_cache:
        return _stats_cache[key]

    data = _get(
        f"https://site.api.espn.com/apis/site/v2/sports/{sport_slug}/{league_slug}/teams/{team_id}/statistics"
    )
    result: dict = {}
    for split in data.get("splits", {}).get("categories", []):
        for stat in split.get("stats", []):
            name = stat.get("name", "")
            val  = stat.get("value")
            disp = stat.get("displayValue", "")
            if name:
                result[name] = disp or val

    _stats_cache[key] = result
    return result


# ── schedule / results ────────────────────────────────────────────────────────

def _get_schedule(sport_slug: str, league_slug: str, team_id: str) -> list[dict]:
    key = (sport_slug, league_slug, team_id)
    if key in _schedule_cache:
        return _schedule_cache[key]
    data = _get(
        f"https://site.api.espn.com/apis/site/v2/sports/{sport_slug}/{league_slug}/teams/{team_id}/schedule"
    )
    events = data.get("events", [])
    _schedule_cache[key] = events
    return events


def _completed(events: list[dict]) -> list[dict]:
    return [
        e for e in events
        if e.get("competitions", [{}])[0].get("status", {}).get("type", {}).get("completed", False)
    ]


def _parse_result(event: dict, our_team_id: str) -> dict:
    comp  = event["competitions"][0]
    comps = comp.get("competitors", [])
    if len(comps) < 2:
        return {}
    home, away = comps[0], comps[1]
    hs  = _score_str(home.get("score"))
    as_ = _score_str(away.get("score"))
    hname = home.get("team", {}).get("displayName", "?")
    aname = away.get("team", {}).get("displayName", "?")
    is_home = str(home.get("team", {}).get("id")) == our_team_id
    try:
        our_score = int(hs)
        opp_score = int(as_)
        if not is_home:
            our_score, opp_score = opp_score, our_score
    except ValueError:
        our_score = opp_score = None
    wl = "?"
    if our_score is not None and opp_score is not None:
        wl = "G" if our_score > opp_score else ("E" if our_score == opp_score else "P")
    return {
        "label":  f"{hname} {hs}-{as_} {aname}",
        "result": wl,
        "home":   is_home,
        "gf":     our_score,
        "ga":     opp_score,
        "total":  (our_score + opp_score) if our_score is not None and opp_score is not None else None,
        "opp_id": str((away if is_home else home).get("team", {}).get("id", "")),
    }


def _last_n_results(events: list[dict], team_id: str, n: int = 10) -> list[dict]:
    done = _completed(events)[-n:]
    return [r for e in done if (r := _parse_result(e, team_id))]


# ── derived historical stats ──────────────────────────────────────────────────

def _historical_stats(results: list[dict], is_home: bool | None = None) -> dict:
    """
    Compute Over/Under and BTTS rates from a list of parsed results.
    is_home=True filters to home games, False away, None uses all.
    """
    filtered = results
    if is_home is not None:
        filtered = [r for r in results if r.get("home") == is_home]

    played = len(filtered)
    if played == 0:
        return {}

    goals_list  = [r["total"] for r in filtered if r.get("total") is not None]
    gf_list     = [r["gf"]    for r in filtered if r.get("gf")    is not None]
    ga_list     = [r["ga"]    for r in filtered if r.get("ga")    is not None]

    over25  = sum(1 for g in goals_list if g >  2.5)
    over35  = sum(1 for g in goals_list if g >  3.5)
    under25 = sum(1 for g in goals_list if g <= 2.5)
    btts    = sum(1 for r in filtered   if r.get("gf", 0) and r.get("ga", 0))
    cs      = sum(1 for r in filtered   if r.get("ga") == 0)   # clean sheets
    fts     = sum(1 for r in filtered   if r.get("gf") == 0)   # failed to score

    avg_total = round(sum(goals_list) / len(goals_list), 2) if goals_list else None
    avg_gf    = round(sum(gf_list)    / len(gf_list),    2) if gf_list    else None
    avg_ga    = round(sum(ga_list)    / len(ga_list),    2) if ga_list    else None

    return {
        "played":       played,
        "avg_gf":       avg_gf,
        "avg_ga":       avg_ga,
        "avg_total":    avg_total,
        "over25_pct":   _pct(over25,  played),
        "over35_pct":   _pct(over35,  played),
        "under25_pct":  _pct(under25, played),
        "btts_pct":     _pct(btts,    played),
        "cs_pct":       _pct(cs,      played),
        "fts_pct":      _pct(fts,     played),
        "raw": {
            "over25": over25, "over35": over35, "under25": under25,
            "btts": btts, "cs": cs, "fts": fts,
        },
    }


# ── injuries ──────────────────────────────────────────────────────────────────

def _get_injuries(sport_slug: str, league_slug: str, team_id: str) -> list[str]:
    data = _get(
        f"https://site.api.espn.com/apis/site/v2/sports/{sport_slug}/{league_slug}/teams/{team_id}/injuries"
    )
    injured = []
    for inj in (data.get("injuries") or []):
        name   = inj.get("athlete", {}).get("displayName", "?")
        status = inj.get("status", "")
        desc   = inj.get("shortComment") or inj.get("longComment") or ""
        injured.append(f"{name} ({status}{': ' + desc if desc else ''})")
    return injured[:8]


# ── H2H ──────────────────────────────────────────────────────────────────────

def _h2h(events: list[dict], team1_id: str, team2_id: str, n: int = 5) -> list[dict]:
    meetings = []
    for e in reversed(_completed(events)):
        comp  = e["competitions"][0]
        comps = comp.get("competitors", [])
        if len(comps) < 2:
            continue
        ids = {str(c.get("team", {}).get("id", "")) for c in comps}
        if team1_id in ids and team2_id in ids:
            home, away = comps[0], comps[1]
            hs  = _score_str(home.get("score"))
            as_ = _score_str(away.get("score"))
            label = f"{home['team'].get('displayName','?')} {hs}-{as_} {away['team'].get('displayName','?')}"
            try:
                total = int(hs) + int(as_)
                meetings.append({"label": label, "total": total})
            except ValueError:
                meetings.append({"label": label, "total": None})
        if len(meetings) >= n:
            break
    return meetings


# ── Tennis ────────────────────────────────────────────────────────────────────

def _build_tennis_index(tour: str) -> None:
    if tour in _tennis_tours_built:
        return
    _tennis_tours_built.add(tour)
    data = _get(
        f"https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/athletes",
        params={"limit": 500, "active": True},
    )
    for a in data.get("athletes", []):
        pid = str(a.get("id", ""))
        if not pid:
            continue
        display  = (a.get("displayName") or "").lower()
        rank_raw = a.get("rank") or a.get("ranking") or {}
        rank     = rank_raw.get("current") if isinstance(rank_raw, dict) else rank_raw
        country_raw = a.get("citizenship") or a.get("country") or {}
        country  = (
            country_raw.get("displayName") or country_raw.get("name") or ""
            if isinstance(country_raw, dict) else str(country_raw)
        )
        entry = {"id": pid, "tour": tour, "ranking": rank, "country": country}
        if display:
            _tennis_players.setdefault(display, entry)
        last = display.split()[-1] if display else ""
        if last:
            _tennis_players.setdefault(last, entry)


def _find_tennis_player(name: str) -> dict | None:
    for tour in ("atp", "wta"):
        _build_tennis_index(tour)
    name_l = name.lower().strip()
    if name_l in _tennis_players:
        return _tennis_players[name_l]
    if "," in name_l:
        last, rest = name_l.split(",", 1)
        first = rest.strip()
        last  = last.strip()
        for key in [f"{first} {last}", last, f"{last} {first}"]:
            if key and key in _tennis_players:
                return _tennis_players[key]
    best, best_r = None, 0.0
    for key, val in _tennis_players.items():
        r = SequenceMatcher(None, name_l, key).ratio()
        if r > best_r:
            best_r, best = r, val
    return best if best_r >= 0.70 else None


def _fetch_tennis_player_stats(player_id: str, tour: str) -> dict:
    """Fetch recent results and statistics for a tennis player."""
    data = _get(
        f"https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/athletes/{player_id}/statistics"
    )
    stats: dict = {}
    for cat in data.get("splits", {}).get("categories", []):
        for s in cat.get("stats", []):
            name = s.get("name", "")
            val  = s.get("displayValue") or s.get("value")
            if name:
                stats[name] = val
    return stats


def fetch_tennis_event_context(event_name: str) -> str:
    parts = re.split(r"\s+vs\.?\s+|\s+v\.?\s+", event_name, flags=re.I)
    if len(parts) != 2:
        return ""

    lines = []
    players_data = []
    for name in parts:
        name   = name.strip()
        player = _find_tennis_player(name)
        if player:
            tour    = player["tour"].upper()
            rank    = player.get("ranking")
            country = player.get("country", "")
            rank_s  = f"#{rank}" if rank else "ranking no disponible"
            country_s = f" ({country})" if country else ""
            line = f"  {name}{country_s} — {tour} Ranking {rank_s}"

            # Try to get win stats
            pstats = _fetch_tennis_player_stats(player["id"], player["tour"])
            if pstats:
                wins_s   = pstats.get("wins", pstats.get("matchesWon", ""))
                losses_s = pstats.get("losses", pstats.get("matchesLost", ""))
                if wins_s or losses_s:
                    line += f"  |  Temporada: {wins_s}V-{losses_s}P"
            lines.append(line)
            players_data.append({"name": name, "rank": rank, "tour": player["tour"]})
        else:
            lines.append(f"  {name}: sin datos ESPN (usa conocimiento de training)")
            players_data.append({"name": name, "rank": None, "tour": None})

    # Ranking difference context
    if len(players_data) == 2:
        r1 = players_data[0].get("rank")
        r2 = players_data[1].get("rank")
        if r1 and r2:
            diff = abs(int(r1) - int(r2))
            fav  = players_data[0]["name"] if int(r1) < int(r2) else players_data[1]["name"]
            lines.append(f"  Diferencia de ranking: {diff} puestos (favorito: {fav})")

    return "\n".join(lines) if lines else ""


# ── main public function ──────────────────────────────────────────────────────

def fetch_event_context(event_name: str, sport: str) -> str:
    """
    Return a comprehensive statistical context block for Claude.
    Includes: season record, Over/Under rates, BTTS rates, clean sheet %,
              home/away splits, last-10 results, H2H, injuries, advanced stats.
    """
    sport_l = sport.lower()

    if any(k in sport_l for k in ("tenis", "tennis")):
        return fetch_tennis_event_context(event_name)

    parts = re.split(r"\s+vs\.?\s+|\s+v\.?\s+", event_name, flags=re.I)
    if len(parts) != 2:
        return ""

    name1, name2 = parts[0].strip(), parts[1].strip()
    entry1 = _find_team(name1, sport)
    entry2 = _find_team(name2, sport)

    if not entry1 and not entry2:
        return ""

    sections: list[str] = []

    def _team_section(name: str, entry: tuple | None, is_home_team: bool) -> str:
        if not entry:
            return f"  {name}: sin datos disponibles en ESPN."
        sport_slug, league_slug, tid = entry

        rec      = _team_record(sport_slug, league_slug, tid)
        events   = _get_schedule(sport_slug, league_slug, tid)
        results  = _last_n_results(events, tid, 15)   # last 15 for better stats
        results5 = results[-5:]

        # ── Season stats ─────────────────────────────────────────────────────
        lines = [f"  {name}:"]
        if rec:
            pos  = rec.get("position", "?")
            pts  = rec.get("points", "?")
            pl   = rec.get("played", "?") or 1
            w    = rec.get("won", "?")
            d    = rec.get("drawn", "?")
            l    = rec.get("lost", "?")
            gf   = rec.get("gf", "?")
            ga   = rec.get("ga", "?")
            gpg  = round(gf  / pl, 2) if isinstance(gf, int)  and isinstance(pl, int)  else "?"
            gapg = round(ga  / pl, 2) if isinstance(ga, int)  and isinstance(pl, int)  else "?"
            lines.append(
                f"    Temporada: {pos}° · {pts}pts · {pl}PJ · {w}V {d}E {l}P · "
                f"GF:{gf}({gpg}/pj) GC:{ga}({gapg}/pj)"
            )
            # Home/away season split
            hp = rec.get("home_played", 0)
            ap = rec.get("away_played", 0)
            if hp or ap:
                hw, hd_, hl = rec.get("home_won",0), rec.get("home_drawn",0), rec.get("home_lost",0)
                hgf, hga    = rec.get("home_gf",0), rec.get("home_ga",0)
                aw, ad_, al = rec.get("away_won",0), rec.get("away_drawn",0), rec.get("away_lost",0)
                agf, aga    = rec.get("away_gf",0), rec.get("away_ga",0)
                hgpg = round(hgf/hp,2) if hp else "?"
                hgapg= round(hga/hp,2) if hp else "?"
                agpg = round(agf/ap,2) if ap else "?"
                agapg= round(aga/ap,2) if ap else "?"
                lines.append(
                    f"    Casa ({hp}PJ): {hw}V {hd_}E {hl}P GF:{hgf}({hgpg}/pj) GC:{hga}({hgapg}/pj)"
                )
                lines.append(
                    f"    Fuera ({ap}PJ): {aw}V {ad_}E {al}P GF:{agf}({agpg}/pj) GC:{aga}({agapg}/pj)"
                )

        # ── Over/Under + BTTS desde historial completo ────────────────────
        if results:
            all_stats  = _historical_stats(results)
            home_stats = _historical_stats(results, is_home=True)
            away_stats = _historical_stats(results, is_home=False)

            context_stats = home_stats if is_home_team else away_stats
            context_label = "en casa" if is_home_team else "de visitante"

            if all_stats:
                lines.append(
                    f"    Histórico últimos {all_stats['played']} partidos · "
                    f"Media goles total: {all_stats.get('avg_total','?')} "
                    f"(anotados: {all_stats.get('avg_gf','?')} encajados: {all_stats.get('avg_ga','?')})"
                )
                lines.append(
                    f"    Over 2.5: {all_stats.get('over25_pct','?')} | "
                    f"Over 3.5: {all_stats.get('over35_pct','?')} | "
                    f"Under 2.5: {all_stats.get('under25_pct','?')} | "
                    f"BTTS: {all_stats.get('btts_pct','?')} | "
                    f"Portería cero: {all_stats.get('cs_pct','?')} | "
                    f"Sin marcar: {all_stats.get('fts_pct','?')}"
                )
            if context_stats:
                lines.append(
                    f"    {context_label.capitalize()} (ult.{context_stats['played']}): "
                    f"Over 2.5: {context_stats.get('over25_pct','?')} | "
                    f"BTTS: {context_stats.get('btts_pct','?')} | "
                    f"CS: {context_stats.get('cs_pct','?')} | "
                    f"Media goles: {context_stats.get('avg_total','?')}"
                )

        # ── Advanced stats (shots, xG, etc.) ─────────────────────────────
        if rec:
            sport_slug2, league_slug2, tid2 = entry
            adv = _team_statistics(sport_slug2, league_slug2, tid2)
            if adv:
                interesting = [
                    "shotsPerGame", "shotsOnTargetPerGame", "possessionPct",
                    "avgGoals", "cleanSheets", "scoringFirst", "yellowCards",
                    "offensiveRating", "defensiveRating", "pace",
                    "ERA", "battingAverage", "saves", "savePercentage",
                    "powerplayPct", "penaltyKillPct",
                ]
                found = {k: adv[k] for k in interesting if k in adv}
                if found:
                    stat_parts = [f"{k}: {v}" for k, v in list(found.items())[:8]]
                    lines.append(f"    Stats avanzadas: {' | '.join(stat_parts)}")

        # ── Recent form (last 5) ──────────────────────────────────────────
        wins5   = sum(1 for r in results5 if r.get("result") == "G")
        draws5  = sum(1 for r in results5 if r.get("result") == "E")
        losses5 = sum(1 for r in results5 if r.get("result") == "P")
        form_str = " ".join(r.get("result", "?") for r in results5)
        gf5      = [r["gf"] for r in results5 if r.get("gf") is not None]
        ga5      = [r["ga"] for r in results5 if r.get("ga") is not None]
        gf5_avg  = round(sum(gf5)/len(gf5), 1) if gf5 else "?"
        ga5_avg  = round(sum(ga5)/len(ga5), 1) if ga5 else "?"

        lines.append(
            f"    Forma ult.5: {form_str} ({wins5}V-{draws5}E-{losses5}P) · "
            f"{gf5_avg} goles/pj · {ga5_avg} encajados/pj"
        )
        if results5:
            lines.append(f"    Resultados: {' | '.join(r['label'] for r in results5)}")

        # ── Injuries ──────────────────────────────────────────────────────
        injuries = _get_injuries(sport_slug, league_slug, tid)
        if injuries:
            lines.append(f"    Bajas/dudas: {', '.join(injuries)}")

        return "\n".join(lines)

    sections.append(_team_section(name1, entry1, is_home_team=True))
    sections.append(_team_section(name2, entry2, is_home_team=False))

    # ── H2H ───────────────────────────────────────────────────────────────────
    if entry1 and entry2:
        sport_slug1, league_slug1, tid1 = entry1
        _, _, tid2 = entry2
        events1 = _get_schedule(sport_slug1, league_slug1, tid1)
        meetings = _h2h(events1, tid1, tid2, 5)
        if meetings:
            h2h_labels  = [m["label"] for m in meetings]
            h2h_totals  = [m["total"] for m in meetings if m.get("total") is not None]
            avg_h2h     = round(sum(h2h_totals)/len(h2h_totals), 1) if h2h_totals else "?"
            over25_h2h  = sum(1 for t in h2h_totals if t > 2.5)
            btts_h2h    = sum(
                1 for e in meetings
                if e.get("total") is not None
                # approximate BTTS: label contains x-y with both > 0
                and re.search(r"[1-9]-[1-9]", e.get("label", ""))
            )
            sections.append(
                f"  H2H últimos {len(meetings)}: {' | '.join(h2h_labels)}\n"
                f"  H2H media goles: {avg_h2h} | Over 2.5: {over25_h2h}/{len(meetings)} | BTTS aprox: {btts_h2h}/{len(meetings)}"
            )
        else:
            sections.append("  Historial directo: sin datos recientes en ESPN")

    return "\n".join(sections)

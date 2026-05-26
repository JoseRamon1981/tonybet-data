"""
Comprehensive team context fetcher using ESPN's unofficial API.
Provides: season record + position, recent results, goals avg,
          home/away splits (season + last 5), H2H, injuries.
For tennis: ATP/WTA player ranking lookup.
No API key required.
"""
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
# ORDER MATTERS: domestic leagues first so they take priority in the team index.
# European comps are indexed last and will NOT overwrite existing entries.

_LEAGUES: dict[str, list[tuple[str, str]]] = {
    "Futbol": [
        ("soccer", "eng.1"),          # Premier League
        ("soccer", "esp.1"),          # La Liga
        ("soccer", "ger.1"),          # Bundesliga
        ("soccer", "ita.1"),          # Serie A
        ("soccer", "fra.1"),          # Ligue 1
        ("soccer", "ned.1"),          # Eredivisie
        ("soccer", "uefa.champions"), # UCL  — indexed last, won't overwrite
        ("soccer", "uefa.europa"),    # UEL  — indexed last, won't overwrite
    ],
    "Baloncesto": [("basketball", "nba")],
    "Hockey hielo": [("hockey", "nhl")],
    "Beisbol": [("baseball", "mlb")],
    "Futbol americano": [("football", "nfl")],
}

# ── caches ────────────────────────────────────────────────────────────────────

# name_lower -> (sport_slug, league_slug, team_id)
_team_index: dict[str, tuple[str, str, str]] = {}
_indexed_sports: set[str] = set()

# (sport_slug, league_slug, team_id) -> team record dict
_record_cache: dict[tuple, dict] = {}

# (sport_slug, league_slug, team_id) -> list of events
_schedule_cache: dict[tuple, list] = {}

# ── Tennis player caches ──────────────────────────────────────────────────────

_tennis_players: dict[str, dict] = {}   # name_key -> {id, tour, ranking, country}
_tennis_tours_built: set[str] = set()


# ── helpers ───────────────────────────────────────────────────────────────────

def _get(url: str, params: dict | None = None):
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


def _int(val, default=0) -> int:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


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
            t = entry.get("team", {})
            tid = str(t.get("id", ""))
            for key in ["displayName", "name", "shortDisplayName", "abbreviation"]:
                val = (t.get(key) or "").lower()
                # IMPORTANT: don't overwrite — domestic leagues come first and win
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


# ── season record (position + stats) ─────────────────────────────────────────

def _team_record(sport_slug: str, league_slug: str, team_id: str) -> dict:
    """
    Fetch team's season record from the team endpoint.
    Returns: position, points, played, won, drawn, lost, gf, ga,
             + home_* and away_* splits.
    """
    key = (sport_slug, league_slug, team_id)
    if key in _record_cache:
        return _record_cache[key]

    data = _get(
        f"https://site.api.espn.com/apis/site/v2/sports/{sport_slug}/{league_slug}/teams/{team_id}"
    )
    team = data.get("team", {})
    items = team.get("record", {}).get("items", [])

    if not items:
        _record_cache[key] = {}
        return {}

    # Use the "total" record item
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
        # Season home splits
        "home_played": _int(stats.get("homeGamesPlayed", 0)),
        "home_won":    _int(stats.get("homeWins", 0)),
        "home_drawn":  _int(stats.get("homeTies", 0)),
        "home_lost":   _int(stats.get("homeLosses", 0)),
        "home_gf":     _int(stats.get("homePointsFor", 0)),
        "home_ga":     _int(stats.get("homePointsAgainst", 0)),
        # Season away splits
        "away_played": _int(stats.get("awayGamesPlayed", 0)),
        "away_won":    _int(stats.get("awayWins", 0)),
        "away_drawn":  _int(stats.get("awayTies", 0)),
        "away_lost":   _int(stats.get("awayLosses", 0)),
        "away_gf":     _int(stats.get("awayPointsFor", 0)),
        "away_ga":     _int(stats.get("awayPointsAgainst", 0)),
    }
    _record_cache[key] = result
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
        "opp_id": str((away if is_home else home).get("team", {}).get("id", "")),
    }


def _last_n_results(events: list[dict], team_id: str, n: int = 5) -> list[dict]:
    done = _completed(events)[-n:]
    return [r for e in done if (r := _parse_result(e, team_id))]


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

def _h2h(events: list[dict], team1_id: str, team2_id: str, n: int = 5) -> list[str]:
    """Find last N meetings between team1 and team2 from team1's schedule."""
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
            meetings.append(
                f"{home['team'].get('displayName','?')} {hs}-{as_} {away['team'].get('displayName','?')}"
            )
        if len(meetings) >= n:
            break
    return meetings


# ── Tennis (ATP/WTA via ESPN) ─────────────────────────────────────────────────

def _build_tennis_index(tour: str) -> None:
    """Build ATP or WTA player name index from ESPN athletes list."""
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
        display = (a.get("displayName") or "").lower()
        rank_raw = a.get("rank") or a.get("ranking") or {}
        rank = rank_raw.get("current") if isinstance(rank_raw, dict) else rank_raw
        country_raw = a.get("citizenship") or a.get("country") or {}
        country = (
            country_raw.get("displayName") or country_raw.get("name") or ""
            if isinstance(country_raw, dict) else str(country_raw)
        )
        entry = {"id": pid, "tour": tour, "ranking": rank, "country": country}
        # Index by full display name and by last name
        for key in [display]:
            if key:
                _tennis_players.setdefault(key, entry)
        last = display.split()[-1] if display else ""
        if last:
            _tennis_players.setdefault(last, entry)


def _find_tennis_player(name: str) -> dict | None:
    """Match a TonyBet player name (Lastname, Firstname) to ESPN."""
    for tour in ("atp", "wta"):
        _build_tennis_index(tour)

    name_l = name.lower().strip()

    # Direct match
    if name_l in _tennis_players:
        return _tennis_players[name_l]

    # TonyBet format: "Lastname, Firstname" → try both orderings
    if "," in name_l:
        last, rest = name_l.split(",", 1)
        first = rest.strip()
        last  = last.strip()
        for key in [f"{first} {last}", last, f"{last} {first}"]:
            if key and key in _tennis_players:
                return _tennis_players[key]

    # Fuzzy fallback
    best, best_r = None, 0.0
    for key, val in _tennis_players.items():
        r = SequenceMatcher(None, name_l, key).ratio()
        if r > best_r:
            best_r, best = r, val
    return best if best_r >= 0.70 else None


def fetch_tennis_event_context(event_name: str) -> str:
    """Return ATP/WTA ranking context for both players in a tennis match."""
    parts = re.split(r"\s+vs\.?\s+|\s+v\.?\s+", event_name, flags=re.I)
    if len(parts) != 2:
        return ""

    lines = []
    for name in parts:
        name = name.strip()
        player = _find_tennis_player(name)
        if player:
            tour    = player["tour"].upper()
            rank    = player.get("ranking")
            country = player.get("country", "")
            rank_s  = f"#{rank}" if rank else "ranking no disponible"
            country_s = f" ({country})" if country else ""
            lines.append(f"  {name}{country_s} — {tour} Ranking {rank_s}")
        else:
            lines.append(f"  {name}: sin datos ESPN (usa tu conocimiento de training)")

    return "\n".join(lines) if lines else ""


# ── main public function ──────────────────────────────────────────────────────

def fetch_event_context(event_name: str, sport: str) -> str:
    """
    Return a comprehensive context block for Claude.
    For tennis: ATP/WTA ranking lookup.
    For team sports: season record, recent results, H2H, injuries.
    """
    sport_l = sport.lower()

    # Tennis: use dedicated player ranking lookup
    if any(k in sport_l for k in ("tenis", "tennis")):
        return fetch_tennis_event_context(event_name)

    # Team sports: use existing ESPN team data
    parts = re.split(r"\s+vs\.?\s+|\s+v\.?\s+", event_name, flags=re.I)
    if len(parts) != 2:
        return ""

    name1, name2 = parts[0].strip(), parts[1].strip()
    entry1 = _find_team(name1, sport)
    entry2 = _find_team(name2, sport)

    if not entry1 and not entry2:
        return ""

    sections: list[str] = []

    def _team_section(name: str, entry: tuple | None) -> str:
        if not entry:
            return f"  {name}: sin datos disponibles en ESPN."
        sport_slug, league_slug, tid = entry

        # Season record (position, points, full record)
        rec = _team_record(sport_slug, league_slug, tid)

        # Recent schedule (last 5 results)
        events = _get_schedule(sport_slug, league_slug, tid)
        results = _last_n_results(events, tid, 5)

        # Recent form stats
        wins   = sum(1 for r in results if r.get("result") == "G")
        draws  = sum(1 for r in results if r.get("result") == "E")
        losses = sum(1 for r in results if r.get("result") == "P")
        gf_list = [r["gf"] for r in results if r.get("gf") is not None]
        ga_list = [r["ga"] for r in results if r.get("ga") is not None]
        gf_avg  = round(sum(gf_list) / len(gf_list), 1) if gf_list else "?"
        ga_avg  = round(sum(ga_list) / len(ga_list), 1) if ga_list else "?"

        # Last 5: home/away split
        home_res = [r for r in results if r.get("home")]
        away_res = [r for r in results if not r.get("home")]
        home_rec5 = (f"{sum(1 for r in home_res if r['result']=='G')}V-"
                     f"{sum(1 for r in home_res if r['result']=='E')}E-"
                     f"{sum(1 for r in home_res if r['result']=='P')}P")
        away_rec5 = (f"{sum(1 for r in away_res if r['result']=='G')}V-"
                     f"{sum(1 for r in away_res if r['result']=='E')}E-"
                     f"{sum(1 for r in away_res if r['result']=='P')}P")

        lines = [f"  {name}:"]

        # Season standings / record
        if rec:
            pos  = rec.get("position", "?")
            pts  = rec.get("points", "?")
            pl   = rec.get("played", "?")
            w    = rec.get("won", "?")
            d    = rec.get("drawn", "?")
            l    = rec.get("lost", "?")
            gf   = rec.get("gf", "?")
            ga   = rec.get("ga", "?")
            gpg  = round(gf / pl, 2) if isinstance(gf, int) and isinstance(pl, int) and pl else "?"
            gapg = round(ga / pl, 2) if isinstance(ga, int) and isinstance(pl, int) and pl else "?"
            lines.append(
                f"    Temporada: {pos}o · {pts}pts · {pl}PJ · {w}V {d}E {l}P · "
                f"GF:{gf}({gpg}/pj) GC:{ga}({gapg}/pj)"
            )
            # Season home/away record
            hp = rec.get("home_played", 0)
            ap = rec.get("away_played", 0)
            if hp or ap:
                hw  = rec.get("home_won", 0)
                hd  = rec.get("home_drawn", 0)
                hl  = rec.get("home_lost", 0)
                hgf = rec.get("home_gf", 0)
                hga = rec.get("home_ga", 0)
                aw  = rec.get("away_won", 0)
                ad  = rec.get("away_drawn", 0)
                al  = rec.get("away_lost", 0)
                agf = rec.get("away_gf", 0)
                aga = rec.get("away_ga", 0)
                lines.append(
                    f"    Temporada en casa ({hp}PJ): {hw}V {hd}E {hl}P  GF:{hgf} GC:{hga} | "
                    f"Fuera ({ap}PJ): {aw}V {ad}E {al}P  GF:{agf} GC:{aga}"
                )

        # Recent form
        form_str = " ".join(r.get("result", "?") for r in results)
        lines.append(
            f"    Forma ult.5: {form_str} ({wins}V-{draws}E-{losses}P) · "
            f"{gf_avg} goles/pj · {ga_avg} encajados/pj"
        )
        lines.append(f"    Ult.5 en casa: {home_rec5} | Fuera: {away_rec5}")

        if results:
            lines.append(f"    Resultados: {' | '.join(r['label'] for r in results)}")

        # Injuries
        injuries = _get_injuries(sport_slug, league_slug, tid)
        if injuries:
            lines.append(f"    Bajas/dudas: {', '.join(injuries)}")
        else:
            lines.append("    Bajas/dudas: no disponibles en ESPN")

        return "\n".join(lines)

    sections.append(_team_section(name1, entry1))
    sections.append(_team_section(name2, entry2))

    # H2H (search team1's full schedule for games vs team2)
    if entry1 and entry2:
        sport_slug1, league_slug1, tid1 = entry1
        _, _, tid2 = entry2
        events1 = _get_schedule(sport_slug1, league_slug1, tid1)
        h2h = _h2h(events1, tid1, tid2, 5)
        if h2h:
            sections.append(f"  Ult.5 enfrentamientos directos: {' | '.join(h2h)}")
        else:
            sections.append("  Historial directo: sin datos recientes en ESPN")

    return "\n".join(sections)

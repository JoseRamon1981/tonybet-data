"""
The Odds API — fuente fiable de cuotas para 40+ deportes.
Sustituye al scraper de Playwright como fuente principal de datos.

Registro gratuito en https://the-odds-api.com/ (500 req/mes = suficiente para 1 ejecución/día).
Configurar: variable de entorno ODDS_API_KEY o secreto GitHub ODDS_API_KEY.
"""
from __future__ import annotations

import requests
from typing import Optional

from .config import config

BASE = "https://api.the-odds-api.com/v4"

# Deportes a consultar, ordenados por prioridad
# Ajusta esta lista según tu presupuesto de requests de API
SPORT_KEYS: list[str] = [
    # ── Fútbol ───────────────────────────────────────────────────────
    "soccer_england_premier_league",
    "soccer_spain_la_liga",
    "soccer_germany_bundesliga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_netherlands_eredivisie",
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_uefa_europa_conference_league",
    "soccer_spain_segunda_division",
    "soccer_england_efl_champ",
    "soccer_portugal_primeira_liga",
    "soccer_turkey_super_league",
    "soccer_brazil_campeonato",
    "soccer_argentina_primera_division",
    "soccer_mexico_ligamx",
    "soccer_usa_mls",
    # ── Tenis ────────────────────────────────────────────────────────
    "tennis_atp_french_open",
    "tennis_wta_french_open",
    "tennis_atp_wimbledon",
    "tennis_wta_wimbledon",
    "tennis_atp_us_open",
    "tennis_wta_us_open",
    "tennis_atp_australian_open",
    "tennis_wta_australian_open",
    # ── Baloncesto ───────────────────────────────────────────────────
    "basketball_nba",
    "basketball_euroleague",
    "basketball_nba_championship_winner",
    "basketball_ncaab",
    # ── Hockey hielo ─────────────────────────────────────────────────
    "icehockey_nhl",
    "icehockey_sweden_hockey_league",
    "icehockey_khl",
    # ── Béisbol ──────────────────────────────────────────────────────
    "baseball_mlb",
    # ── Fútbol americano ─────────────────────────────────────────────
    "americanfootball_nfl",
    "americanfootball_ncaaf",
    # ── MMA / Boxeo ──────────────────────────────────────────────────
    "mma_mixed_martial_arts",
    "boxing_boxing",
    # ── Rugby ────────────────────────────────────────────────────────
    "rugbyleague_nrl",
    "rugbyunion_premiership",
    "rugbyunion_super_rugby",
    # ── Cricket ──────────────────────────────────────────────────────
    "cricket_international_t20",
    "cricket_ipl",
    "cricket_the_ashes",
    # ── Golf ─────────────────────────────────────────────────────────
    "golf_the_masters_tournament",
    "golf_pga_championship",
    "golf_the_open_championship",
    "golf_us_open",
    # ── Dardos ───────────────────────────────────────────────────────
    "darts_pdc_world_championship",
    # ── Balonmano / Voleibol ─────────────────────────────────────────
    "handball_germany_handball_bundesliga",
    "volleyball_wvl_women",
]

_SPORT_NAMES: dict[str, str] = {
    "soccer":           "Fútbol",
    "tennis":           "Tenis",
    "basketball":       "Baloncesto",
    "icehockey":        "Hockey hielo",
    "baseball":         "Béisbol",
    "americanfootball": "Fútbol americano",
    "mma":              "MMA",
    "boxing":           "Boxeo",
    "rugbyleague":      "Rugby League",
    "rugbyunion":       "Rugby Union",
    "cricket":          "Cricket",
    "golf":             "Golf",
    "darts":            "Dardos",
    "volleyball":       "Voleibol",
    "handball":         "Balonmano",
}

_COMP_NAMES: dict[str, str] = {
    "soccer_england_premier_league":          "Premier League",
    "soccer_spain_la_liga":                   "La Liga",
    "soccer_germany_bundesliga":              "Bundesliga",
    "soccer_italy_serie_a":                   "Serie A",
    "soccer_france_ligue_one":                "Ligue 1",
    "soccer_netherlands_eredivisie":          "Eredivisie",
    "soccer_uefa_champs_league":              "Champions League",
    "soccer_uefa_europa_league":              "Europa League",
    "soccer_uefa_europa_conference_league":   "Conference League",
    "soccer_spain_segunda_division":          "Segunda División",
    "soccer_england_efl_champ":               "Championship",
    "soccer_portugal_primeira_liga":          "Primeira Liga",
    "soccer_turkey_super_league":             "Süper Lig",
    "soccer_brazil_campeonato":               "Brasileirão",
    "soccer_argentina_primera_division":      "Primera División Argentina",
    "soccer_mexico_ligamx":                   "Liga MX",
    "soccer_usa_mls":                         "MLS",
    "tennis_atp_french_open":                 "Roland Garros ATP",
    "tennis_wta_french_open":                 "Roland Garros WTA",
    "tennis_atp_wimbledon":                   "Wimbledon ATP",
    "tennis_wta_wimbledon":                   "Wimbledon WTA",
    "tennis_atp_us_open":                     "US Open ATP",
    "tennis_wta_us_open":                     "US Open WTA",
    "tennis_atp_australian_open":             "Australian Open ATP",
    "tennis_wta_australian_open":             "Australian Open WTA",
    "basketball_nba":                         "NBA",
    "basketball_euroleague":                  "Euroliga",
    "basketball_ncaab":                       "NCAA Baloncesto",
    "icehockey_nhl":                          "NHL",
    "icehockey_sweden_hockey_league":         "SHL",
    "icehockey_khl":                          "KHL",
    "baseball_mlb":                           "MLB",
    "americanfootball_nfl":                   "NFL",
    "americanfootball_ncaaf":                 "NCAA Fútbol Americano",
    "mma_mixed_martial_arts":                 "MMA/UFC",
    "boxing_boxing":                          "Boxeo",
    "rugbyleague_nrl":                        "NRL",
    "rugbyunion_premiership":                 "Premiership Rugby",
    "rugbyunion_super_rugby":                 "Super Rugby",
    "cricket_international_t20":              "T20 Internacional",
    "cricket_ipl":                            "IPL Cricket",
    "cricket_the_ashes":                      "The Ashes",
    "golf_the_masters_tournament":            "The Masters",
    "golf_pga_championship":                  "PGA Championship",
    "golf_the_open_championship":             "The Open",
    "golf_us_open":                           "US Open Golf",
    "darts_pdc_world_championship":           "PDC Darts",
    "handball_germany_handball_bundesliga":   "Bundesliga Balonmano",
    "volleyball_wvl_women":                   "Liga Voleibol",
}

# Orden de preferencia de casas de apuestas (Pinnacle = menor margen = cuotas más fiables)
_BOOKMAKER_PREF: list[str] = [
    "pinnacle",
    "betfair_ex_eu",
    "betfair",
    "marathonbet",
    "unibet_eu",
    "unibet",
    "bet365",
    "betway",
    "williamhill",
    "bwin",
    "betfair_ex_uk",
    "paddypower",
    "skybet",
    "888sport",
    "ladbrokes",
]

_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = "TonybetAdvisor/2.0"


def _sport_name(key: str) -> str:
    prefix = key.split("_")[0]
    return _SPORT_NAMES.get(prefix, prefix.title())


def _best_bookmaker(bookmakers: list[dict]) -> dict | None:
    by_key = {b["key"]: b for b in bookmakers}
    for pref in _BOOKMAKER_PREF:
        if pref in by_key:
            return by_key[pref]
    return bookmakers[0] if bookmakers else None


def _parse_market(market: dict) -> Optional[dict]:
    key = market.get("key", "")
    outcomes = market.get("outcomes", [])

    selections = []
    for o in outcomes:
        name  = o.get("name", "")
        price = o.get("price", 0.0)
        point = o.get("point")

        if price < 1.01:
            continue

        if key == "totals":
            label = f"{'Over' if name == 'Over' else 'Under'} {point}" if point is not None else name
        elif key == "spreads":
            label = f"{name} {point:+.1f}" if point is not None else name
        else:
            label = name

        selections.append({"name": label, "odds": round(float(price), 2)})

    if not selections:
        return None

    if key == "h2h":
        market_name = "1X2" if len(selections) == 3 else "Ganador"
    elif key == "totals":
        market_name = "Totales"
    elif key == "spreads":
        market_name = "Hándicap"
    else:
        market_name = key.replace("_", " ").title()

    return {"name": market_name, "selections": selections}


def _parse_event(raw: dict, sport_key: str) -> Optional[dict]:
    home = raw.get("home_team", "")
    away = raw.get("away_team", "")
    if not home or not away:
        return None

    bookmakers = raw.get("bookmakers", [])
    bm = _best_bookmaker(bookmakers)
    if not bm:
        return None

    markets = []
    for m in bm.get("markets", []):
        parsed = _parse_market(m)
        if parsed:
            markets.append(parsed)

    if not markets:
        return None

    return {
        "id":          raw.get("id", ""),
        "name":        f"{home} vs {away}",
        "sport":       _sport_name(sport_key),
        "competition": _COMP_NAMES.get(sport_key, sport_key.replace("_", " ").title()),
        "starts_at":   raw.get("commence_time", ""),
        "markets":     markets,
        "bookmaker":   bm.get("title", ""),
    }


def fetch_events(api_key: str, max_requests: int = 40) -> list[dict]:
    """
    Descarga eventos con cuotas de The Odds API para todos los deportes configurados.

    Tier gratuito (500 req/mes): usa max_requests=15 para ejecuciones diarias.
    Tier de pago: aumenta max_requests o ponlo en 0 para sin límite.
    """
    if not api_key:
        print("  ⚠ ODDS_API_KEY no configurada — sin datos de The Odds API")
        return []

    print("  → Consultando deportes disponibles en The Odds API…")
    try:
        r = _SESSION.get(
            f"{BASE}/sports",
            params={"apiKey": api_key, "all": "false"},
            timeout=15,
        )
        if r.ok:
            active_keys = {s["key"] for s in r.json() if s.get("active")}
            query_sports = [k for k in SPORT_KEYS if k in active_keys]
            remaining_header = r.headers.get("x-requests-remaining", "?")
            print(f"  → {len(query_sports)} deportes activos · requests restantes: {remaining_header}")
        else:
            print(f"  ⚠ Error al obtener deportes: {r.status_code}")
            query_sports = SPORT_KEYS
    except Exception as e:
        print(f"  ⚠ Error conectando con The Odds API: {e}")
        return []

    all_events: list[dict] = []
    requests_used = 1  # ya gastamos 1 en /sports

    for sport_key in query_sports:
        if max_requests > 0 and requests_used >= max_requests:
            print(f"  → Límite de {max_requests} requests alcanzado — resto de deportes omitidos")
            break

        try:
            r = _SESSION.get(
                f"{BASE}/sports/{sport_key}/odds",
                params={
                    "apiKey":      api_key,
                    "regions":     "eu,uk",
                    "markets":     "h2h,totals,spreads",
                    "oddsFormat":  "decimal",
                    "dateFormat":  "iso",
                },
                timeout=20,
            )
            requests_used += 1

            remaining = r.headers.get("x-requests-remaining", "?")

            if r.status_code == 401:
                print("  ✗ ODDS_API_KEY inválida — verifica la clave en GitHub Secrets")
                break
            if r.status_code == 422:
                continue  # deporte no disponible actualmente
            if not r.ok:
                print(f"  ⚠ Error {r.status_code} en {sport_key}")
                continue

            events_data = r.json()
            count = 0
            for raw in events_data:
                parsed = _parse_event(raw, sport_key)
                if parsed:
                    all_events.append(parsed)
                    count += 1

            if count:
                comp = _COMP_NAMES.get(sport_key, sport_key)
                print(f"  ✓ {comp}: {count} eventos (requests restantes: {remaining})")

        except Exception as e:
            print(f"  ⚠ Error en {sport_key}: {e}")

    print(f"  → Total: {len(all_events)} eventos en {requests_used} requests API")
    return all_events

"""
Tonybet Betting Advisor — CLI entry point.

Modes:
  advisor   (default) — scrape + analyse + show recommendations
  autobet             — same as advisor + place bets (asks confirmation)
  demo                — use sample data, no Tonybet login needed
  stats               — show P&L history and performance stats
  result              — mark a bet as won/lost/void
"""
import asyncio
import os
import sys

from .config import config
from .analyzer import BetAnalysis


# ── display helpers ───────────────────────────────────────────────────────────

def _print_header():
    print("\n" + "=" * 60)
    print("   TONYBET BETTING ADVISOR  (powered by Claude AI)")
    print("=" * 60)


def _format_datetime(raw: str) -> str:
    """Convert ISO datetime to readable Spanish format."""
    if not raw:
        return "Hora desconocida"
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(raw.replace("Z", ""))
        return dt.strftime("%d/%m/%Y  %H:%M")
    except Exception:
        return raw


def _market_navigation(market: str, selection: str) -> str:
    """Return step-by-step instructions for finding a market on Tonybet."""
    m = market.lower()
    s = selection.lower()

    if "over/under" in m or "goles" in m or "totales" in m or "puntos" in m:
        line = selection.replace("Over ", "Más de ").replace("Under ", "Menos de ")
        return (
            f"1) Busca el partido en Tonybet\n"
            f"      2) Entra al partido (click en el nombre)\n"
            f"      3) Arriba verás pestañas: PRINCIPAL, GOLES, HANDICAP... → pulsa 'GOLES'\n"
            f"      4) Busca 'Total de goles' y selecciona '{line}'"
        )
    if "ambos" in m or "btts" in m or "marcan" in m:
        return (
            f"1) Busca el partido → entra al partido\n"
            f"      2) Pestaña 'PRINCIPAL' o 'MÁS APUESTAS'\n"
            f"      3) Busca 'Ambos equipos marcan' → selecciona '{selection}'"
        )
    if "doble oportunidad" in m or "doble op" in m:
        return (
            f"1) Busca el partido → entra al partido\n"
            f"      2) Pestaña 'PRINCIPAL'\n"
            f"      3) Busca 'Doble oportunidad' → selecciona '{selection}'"
        )
    if "handicap" in m:
        return (
            f"1) Busca el partido → entra al partido\n"
            f"      2) Pestaña 'HANDICAP'\n"
            f"      3) Selecciona '{selection}'"
        )
    if "1x2" in m or "resultado" in m:
        return (
            f"1) Busca el partido en la lista\n"
            f"      2) Las cuotas 1-X-2 aparecen directamente\n"
            f"      3) Pulsa la cuota de '{selection}'"
        )
    if "ganador" in m:
        return (
            f"1) Busca el partido → entra al partido\n"
            f"      2) Pestaña 'PRINCIPAL'\n"
            f"      3) 'Ganador del partido' → selecciona '{selection}'"
        )
    return (
        f"1) Busca el partido → entra al partido\n"
        f"      2) Busca el mercado '{market}' → selecciona '{selection}'"
    )


def _print_recommendations(bets: list[BetAnalysis]):
    if not bets:
        print("\n  No se encontraron value bets en este momento.\n")
        return

    print(f"\n{'='*60}")
    print(f"  APUESTAS DEL DIA: {len(bets)} recomendaciones")
    print(f"{'='*60}")

    for i, b in enumerate(bets, 1):
        ev_pct = b.expected_value * 100
        over_pct = b.overround * 100
        nav = _market_navigation(b.market, b.selection)
        print(f"\n  [{i}] {b.event}")
        print(f"      Hora      : {_format_datetime(b.starts_at)}")
        print(f"      Deporte   : {b.sport}")
        print(f"      Apuesta   : {b.market}  →  {b.selection}")
        print(f"      Cuota     : {b.odds:.2f}  (impl. {b.implied_probability*100:.1f}%)")
        print(f"      Prob.real : {b.estimated_probability*100:.1f}%")
        print(f"      EV        : {ev_pct:+.1f}%  |  Margen book: {over_pct:.1f}%")
        print(f"      Stake rec.: {b.recommended_stake:.2f}€  (Kelly x{config.kelly_fraction})")
        print(f"      Como apostar:")
        print(f"      {nav}")

    total_stake = sum(b.recommended_stake for b in bets)
    print(f"\n  Stake total recomendado: {total_stake:.2f}€")
    print(f"  Limite diario configurado: {config.max_daily_stake:.2f}€")
    if total_stake > config.max_daily_stake:
        print("  AVISO: El stake total supera tu limite diario -- reduce stakes o seleccion.")
    print()


def _ask_confirmation(bets: list[BetAnalysis]) -> list[BetAnalysis]:
    print("¿Qué apuestas quieres colocar? (escribe los números separados por coma, 'all' o 'none')")
    answer = input("  > ").strip().lower()

    if answer == "none" or answer == "":
        return []
    if answer == "all":
        return bets

    selected = []
    for part in answer.split(","):
        try:
            idx = int(part.strip()) - 1
            if 0 <= idx < len(bets):
                selected.append(bets[idx])
        except ValueError:
            pass
    return selected


def _load_demo_events() -> list[dict]:
    """Sample events for testing without Tonybet login."""
    return [
        {
            "id": "1",
            "name": "Real Madrid vs Barcelona",
            "sport": "Fútbol",
            "competition": "La Liga",
            "starts_at": "2025-06-01T20:00:00",
            "markets": [
                {
                    "name": "1X2",
                    "selections": [
                        {"name": "Real Madrid", "odds": 2.10},
                        {"name": "Empate", "odds": 3.40},
                        {"name": "Barcelona", "odds": 3.60},
                    ],
                },
                {
                    "name": "Ambos equipos marcan",
                    "selections": [
                        {"name": "Sí", "odds": 1.72},
                        {"name": "No", "odds": 2.05},
                    ],
                },
            ],
        },
        {
            "id": "2",
            "name": "Manchester City vs Arsenal",
            "sport": "Fútbol",
            "competition": "Premier League",
            "starts_at": "2025-06-02T17:30:00",
            "markets": [
                {
                    "name": "1X2",
                    "selections": [
                        {"name": "Man City", "odds": 1.85},
                        {"name": "Empate", "odds": 3.60},
                        {"name": "Arsenal", "odds": 4.20},
                    ],
                },
            ],
        },
        {
            "id": "3",
            "name": "Novak Djokovic vs Carlos Alcaraz",
            "sport": "Tenis",
            "competition": "Roland Garros",
            "starts_at": "2025-06-03T14:00:00",
            "markets": [
                {
                    "name": "Ganador",
                    "selections": [
                        {"name": "Djokovic", "odds": 2.30},
                        {"name": "Alcaraz", "odds": 1.65},
                    ],
                },
            ],
        },
    ]


# ── ask (natural language query) ─────────────────────────────────────────────

async def _run_ask(question: str):
    """Answer any natural language question about today's events on Tonybet."""
    import json
    from .scraper import TonybetScraper
    from .config import config
    import anthropic

    print(f"\n  Pregunta: {question}")
    print("  Scrapeando Tonybet para obtener datos actuales...\n")

    scraper = TonybetScraper()
    events  = await scraper.scrape()

    if not events:
        print("No se obtuvieron eventos. Comprueba tu conexión.")
        return

    # Build a compact but complete event list for Claude
    compact = []
    for e in events:
        compact.append({
            "nombre":      e.get("name"),
            "deporte":     e.get("sport"),
            "competicion": e.get("competition"),
            "hora":        e.get("starts_at"),
            "mercados":    [
                {
                    "mercado":    m.get("name"),
                    "selecciones": [
                        {"nombre": s.get("name"), "cuota": s.get("odds")}
                        for s in m.get("selections", [])
                    ]
                }
                for m in e.get("markets", [])[:4]
            ],
        })

    events_json = json.dumps(compact, ensure_ascii=False, indent=2)

    prompt = (
        f"Eres un asistente experto en apuestas deportivas. El usuario te hace esta pregunta:\n\n"
        f"  \"{question}\"\n\n"
        f"A continuación tienes TODOS los eventos disponibles ahora mismo en Tonybet ({len(compact)} partidos).\n"
        f"Responde la pregunta del usuario usando únicamente los datos que aparecen aquí.\n"
        f"Sé concreto, claro y organizado. Si la pregunta pide cuotas, inclúyelas.\n"
        f"Si no hay eventos que coincidan, dilo claramente.\n\n"
        f"DATOS DE TONYBET:\n{events_json}"
    )

    client = anthropic.Anthropic(api_key=config.anthropic_api_key)

    # Stream the response for faster feedback
    print("  Consultando a Claude...\n")
    print("─" * 60)
    with client.messages.stream(
        model=config.claude_model,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
    print("\n" + "─" * 60)


# ── preview ──────────────────────────────────────────────────────────────────

async def _run_preview():
    """Scout tomorrow's events with relaxed threshold — shows candidates 70%+."""
    from datetime import datetime, timedelta
    from .scraper import TonybetScraper
    from .form_fetcher import fetch_event_context

    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"\n  Buscando partidos del {tomorrow}...\n")

    scraper = TonybetScraper()
    events = await scraper.scrape()

    # Keep only tomorrow's events
    tomorrow_events = [
        e for e in events
        if str(e.get("starts_at", "")).startswith(tomorrow)
    ]

    if not tomorrow_events:
        print(f"  No hay eventos registrados en Tonybet para el {tomorrow} todavia.")
        print("  Prueba mas tarde — Tonybet suele publicar las cuotas del dia siguiente por la tarde/noche.")
        return

    print(f"  {len(tomorrow_events)} eventos encontrados para manana.\n")

    # Group and sample (same logic as advisor)
    from collections import defaultdict
    FOOTBALL_TOP = [
        "premier league", "la liga", "bundesliga", "serie a", "ligue 1",
        "champions league", "europa league", "eredivisie", "primera division",
    ]
    TENNIS_KEYWORDS = ["tenis", "tennis", "atp", "wta", "roland garros", "wimbledon", "us open", "australian open"]
    OTHER_SPORTS = ["baloncesto", "hockey", "balonmano", "voleibol",
                    "beisbol", "futbol americano", "tenis mesa"]

    def _is_top(e):
        comp  = (e.get("competition") or "").lower()
        sport = (e.get("sport") or "").lower()
        if sport == "futbol":
            return any(t in comp for t in FOOTBALL_TOP)
        if any(k in sport for k in TENNIS_KEYWORDS) or any(k in comp for k in TENNIS_KEYWORDS):
            return True
        return any(s in sport for s in OTHER_SPORTS)

    top = [e for e in tomorrow_events if _is_top(e)]
    by_sport: dict = defaultdict(list)
    for e in top:
        by_sport[e.get("sport", "Otros")].append(e)

    sample: list[dict] = []
    sample += by_sport.get("Futbol", [])[:8]
    for sp, evts in by_sport.items():
        if sp != "Futbol":
            sport_l = sp.lower()
            limit = 8 if any(k in sport_l for k in TENNIS_KEYWORDS) else 4
            sample += evts[:limit]
    if not sample:
        sample = tomorrow_events[:25]

    # Build enriched event list with ESPN data
    import json
    print("  Obteniendo datos reales de equipos desde ESPN...")
    enriched = []
    for e in sample[:25]:
        ctx = fetch_event_context(e.get("name", ""), e.get("sport", ""))
        entry = {
            "name": e.get("name"),
            "sport": e.get("sport"),
            "competition": e.get("competition"),
            "starts_at": e.get("starts_at"),
            "markets": e.get("markets", [])[:3],
        }
        if ctx:
            entry["datos_espn"] = ctx
        enriched.append(entry)

    events_json = json.dumps(enriched, ensure_ascii=False, indent=2)

    import anthropic
    from .config import config
    client = anthropic.Anthropic(api_key=config.anthropic_api_key)

    prompt = (
        "Eres un scout de apuestas deportivas. Tu tarea es hacer un AVANCE de los partidos de MANANA.\n\n"
        "NO es un análisis definitivo — es un vistazo previo para saber qué partidos merecen atención.\n\n"
        "Para cada evento:\n"
        "1. Indica el nivel de interés: ALTO / MEDIO / BAJO\n"
        "2. Señala qué selección/mercado podría tener valor (no hace falta calcular EV exacto)\n"
        "3. Explica en 1-2 líneas por qué — usando la forma reciente si está disponible\n"
        "4. Señala si hay algo que NO sabes (lesiones recientes, contexto de temporada) que podría cambiar el análisis\n\n"
        "TENIS: Para partidos de Grand Slam (Roland Garros, Wimbledon, US Open, AO) usa tu conocimiento\n"
        "de rankings ATP/WTA y especialización en superficie. No necesitas datos ESPN para esto.\n\n"
        "Al final, haz un RANKING de los 3 partidos más prometedores para el análisis completo de mañana.\n\n"
        "Sé directo y breve. No uses tablas largas. Formato simple.\n\n"
        f"EVENTOS DE MAÑANA ({tomorrow}):\n{events_json}"
    )

    print("  Analizando con Claude...\n")
    response = client.messages.create(
        model=config.claude_model,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    analysis_text = response.content[0].text
    print(analysis_text)
    print(f"\n  ({len(sample)} eventos analizados de {len(tomorrow_events)} disponibles para manana)")

    # Save preview to JSON and push to GitHub
    from datetime import datetime as _dt
    from pathlib import Path
    import subprocess, shutil

    data_repo = Path(__file__).parent.parent
    preview_data = {
        "updated_at": _dt.now().strftime("%d/%m/%Y %H:%M"),
        "for_date": tomorrow,
        "analysis": analysis_text,
        "total_events": len(tomorrow_events),
        "analyzed_count": len(sample),
    }
    (data_repo / "preview_latest.json").write_text(
        json.dumps(preview_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        subprocess.run(["git", "add", "preview_latest.json"], cwd=str(data_repo), check=True)
        subprocess.run(["git", "commit", "-m", "advisor: update preview"], cwd=str(data_repo), check=True)
        subprocess.run(["git", "push"], cwd=str(data_repo), check=True)
        print("  Preview publicado en el dashboard web.")
    except Exception as e:
        print(f"  No se pudo publicar el preview: {e}")


# ── main flow ─────────────────────────────────────────────────────────────────

async def run(mode: str = "advisor"):
    _print_header()

    # Validate config
    try:
        if mode != "demo":
            config.validate()
    except ValueError as e:
        print(f"\n  Configuracion incompleta: {e}")
        print("   Crea un archivo .env con las variables requeridas (ver .env.example)\n")
        sys.exit(1)

    bankroll = float(os.getenv("BANKROLL", "200"))

    # Preview mode: scout tomorrow's events with relaxed threshold
    if mode == "preview":
        await _run_preview()
        return

    # 1. Get events
    if mode == "demo":
        print("\n[MODO DEMO] Usando eventos de ejemplo…")
        events = _load_demo_events()
    else:
        from .scraper import TonybetScraper
        scraper = TonybetScraper()
        events = await scraper.scrape()

    if not events:
        print("⚠ No se obtuvieron eventos de Tonybet.")
        print("  Posibles causas:")
        print("  1. Tonybet requiere login para servir datos vía API — verifica credenciales")
        print("  2. La estructura de URLs de la API cambió — revisa los logs de debug de URLs")
        print("  3. El sitio está temporalmente caído o bloqueando bots")
        print("\n  Publicando estado vacío en el dashboard…")
        # Push empty recommendations so dashboard shows "sin datos" instead of stale data
        import json as _json, subprocess
        from pathlib import Path
        from datetime import datetime as _dt
        data_repo = Path(__file__).parent.parent
        empty_snap = {
            "updated_at": _dt.now().strftime("%d/%m/%Y %H:%M"),
            "total": 0,
            "events": [],
            "error": "No se pudieron obtener eventos de Tonybet",
        }
        (data_repo / "events_latest.json").write_text(
            _json.dumps(empty_snap, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        try:
            subprocess.run(["git", "add", "events_latest.json"], cwd=str(data_repo), check=True)
            subprocess.run(["git", "commit", "-m", "advisor: sin eventos (scraper sin datos)"], cwd=str(data_repo), check=True)
            subprocess.run(["git", "push"], cwd=str(data_repo), check=True)
        except Exception:
            pass
        sys.exit(0)  # exit 0 so GitHub Actions doesn't mark as failed

    # 2. Pre-filter: prioritize top leagues + all tennis Grand Slams
    TOP_LEAGUES = [
        # Futbol
        "premier league", "la liga", "bundesliga", "serie a", "ligue 1",
        "champions league", "europa league", "eredivisie", "primera",
        # Baloncesto
        "nba", "euroleague", "acb", "ncaa",
        # Tenis
        "atp", "wta", "roland garros", "wimbledon", "us open", "australian open",
        # Hockey hielo
        "nhl", "khl", "shl",
        # Balonmano
        "handball bundesliga", "liga asobal", "champions league handball",
        # Beisbol
        "mlb",
        # Futbol americano
        "nfl",
        # Voleibol
        "superliga",
    ]
    FOOTBALL_TOP = [
        "premier league", "la liga", "bundesliga", "serie a", "ligue 1",
        "champions league", "europa league", "eredivisie", "primera division",
    ]
    TENNIS_KEYWORDS = ["tenis", "tennis", "atp", "wta", "roland garros", "wimbledon", "us open", "australian open"]
    OTHER_SPORTS = ["baloncesto", "hockey", "balonmano", "voleibol",
                    "beisbol", "futbol americano", "tenis mesa"]

    def _is_top_league(e: dict) -> bool:
        comp  = (e.get("competition") or "").lower()
        sport = (e.get("sport") or "").lower()
        # For football: only top leagues
        if sport == "futbol":
            return any(t in comp for t in FOOTBALL_TOP)
        # For tennis: always include (Grand Slams are priority)
        if any(k in sport for k in TENNIS_KEYWORDS) or any(k in comp for k in TENNIS_KEYWORDS):
            return True
        # For other sports: include all
        return any(s in sport for s in OTHER_SPORTS)

    top_events = [e for e in events if _is_top_league(e)]

    # Sample across sports: up to 8 football + 10 tennis + 3 per other sport
    from collections import defaultdict
    by_sport: dict[str, list] = defaultdict(list)
    for e in top_events:
        by_sport[(e.get("sport") or "Otros")].append(e)

    filtered: list[dict] = []
    filtered += by_sport.get("Futbol", [])[:8]
    for sport, evts in by_sport.items():
        if sport != "Futbol":
            sport_l = sport.lower()
            limit = 10 if any(k in sport_l for k in TENNIS_KEYWORDS) else 3
            filtered += evts[:limit]

    # Fill remaining slots with more football if needed
    if len(filtered) < 30:
        already = {id(e) for e in filtered}
        for e in by_sport.get("Futbol", [])[8:]:
            if len(filtered) >= 30:
                break
            if id(e) not in already:
                filtered.append(e)

    if not filtered:
        filtered = events[:20]
    print(f"  Eventos seleccionados: {len(filtered)}/{len(events)} ({len(by_sport)} deportes)")

    # 3. Analyse with Claude
    from .claude_agent import BettingAdvisor
    advisor = BettingAdvisor(bankroll=bankroll)
    value_bets = advisor.analyse(filtered)

    # 3. Show recommendations
    _print_recommendations(value_bets)

    if mode == "demo":
        return

    # Save and publish results
    from .tracker import record_bets, save_latest_recommendations
    save_latest_recommendations(value_bets)
    if value_bets:
        record_bets(value_bets)

    # Push data to GitHub so the web dashboard updates
    import subprocess, json as _json
    from pathlib import Path
    from datetime import datetime as _dt
    data_repo = Path(__file__).parent.parent

    # Save compact events snapshot for the web dashboard query tab
    compact_events = []
    for e in events:
        compact_events.append({
            "nombre":      e.get("name"),
            "deporte":     e.get("sport"),
            "competicion": e.get("competition"),
            "hora":        e.get("starts_at"),
            "mercados": [
                {
                    "mercado": m.get("name"),
                    "selecciones": [
                        {"nombre": s.get("name"), "cuota": s.get("odds")}
                        for s in m.get("selections", [])
                    ]
                }
                for m in e.get("markets", [])[:4]
            ],
        })
    events_snap = {
        "updated_at": _dt.now().strftime("%d/%m/%Y %H:%M"),
        "total": len(compact_events),
        "events": compact_events,
    }
    (data_repo / "events_latest.json").write_text(
        _json.dumps(events_snap, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        subprocess.run(["git", "add", "recommendations_latest.json", "bets_log.json", "events_latest.json"], cwd=str(data_repo), check=True)
        subprocess.run(["git", "commit", "-m", "advisor: update recommendations"], cwd=str(data_repo), check=True)
        subprocess.run(["git", "push"], cwd=str(data_repo), check=True)
        print("  Dashboard web actualizado en GitHub.")
    except Exception as e:
        print(f"  No se pudo publicar en GitHub: {e}")

    # Auto-generate tomorrow's preview after every advisor run
    print("\n  Generando preview de manana...")
    try:
        await _run_preview()
    except Exception as e:
        print(f"  No se pudo generar el preview: {e}")

    if not value_bets:
        return

    # 4. Bet execution modes
    if mode in ("autobet", "dryrun"):
        selected = _ask_confirmation(value_bets)
        if not selected:
            print("Sin apuestas seleccionadas. Saliendo.")
            return

        total = sum(b.recommended_stake for b in selected)
        if total > config.max_daily_stake:
            print(f"\n  Stake total ({total:.2f}€) supera el límite diario ({config.max_daily_stake:.2f}€).")
            print("   Ajusta los límites en .env o reduce la selección.\n")
            return

        from .bet_executor import BetExecutor
        executor = BetExecutor()

        if mode == "dryrun":
            print("\n[SIMULACION] Navegando a Tonybet para verificar que encuentra cada apuesta...")
            print("  El navegador se abrirá. Comprueba que llega al mercado correcto.")
            print("  NO se confirmará ninguna apuesta.\n")
            placed = await executor.place_bets(selected, dry_run=True)
            if placed:
                print(f"\n  Simulacion OK: {len(placed)}/{len(selected)} apuestas localizadas correctamente.")
                print("  Cuando quieras apostar de verdad, usa:  python -m tonybet_advisor autobet")
            else:
                print("\n  La simulacion no encontró las apuestas. Revisa el navegador e informa del problema.")
            return

        # autobet: real bets with explicit confirmation
        print("\n¿Realizar apuestas REALES? Escribe 'CONFIRMAR' para proceder (cualquier otra cosa cancela):")
        confirm = input("  > ").strip()
        if confirm != "CONFIRMAR":
            print("Apuestas canceladas.")
            return

        placed = await executor.place_bets(selected, dry_run=False)
        print(f"\n  {len(placed)}/{len(selected)} apuestas colocadas correctamente.")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "advisor"

    if mode == "stats":
        from .tracker import print_stats
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        print_stats(days)
        return

    if mode == "result":
        # Usage: python -m tonybet_advisor result "Real Madrid vs Barcelona" "Real Madrid" won
        if len(sys.argv) < 5:
            print("Uso: python -m tonybet_advisor result \"<evento>\" \"<selección>\" <won|lost|void>")
            sys.exit(1)
        from .tracker import update_result
        update_result(sys.argv[2], sys.argv[3], sys.argv[4])
        return

    if mode == "ask":
        if len(sys.argv) < 3:
            print("Uso: python -m tonybet_advisor ask \"tu pregunta aqui\"")
            print("Ejemplos:")
            print("  python -m tonybet_advisor ask \"que hay en la liga española hoy\"")
            print("  python -m tonybet_advisor ask \"cuotas del partido de tenis mas interesante\"")
            print("  python -m tonybet_advisor ask \"hay partidos de la NBA esta noche?\"")
            sys.exit(1)
        question = " ".join(sys.argv[2:])
        asyncio.run(_run_ask(question))
        return

    valid_modes = ("advisor", "autobet", "dryrun", "preview", "demo")
    if mode not in valid_modes:
        print(f"Uso: python -m tonybet_advisor [{'|'.join(valid_modes)}|ask|stats|result]")
        sys.exit(1)
    asyncio.run(run(mode))


if __name__ == "__main__":
    main()

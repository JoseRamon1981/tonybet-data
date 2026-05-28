"""
Tonybet Betting Advisor — CLI entry point.

Modos:
  advisor   (por defecto) — obtener cuotas + analizar + mostrar recomendaciones
  autobet                 — igual que advisor + colocar apuestas (pide confirmación)
  demo                    — usa datos de ejemplo, sin necesidad de credenciales
  stats                   — muestra historial P&L y estadísticas
  result                  — marcar una apuesta como ganada/perdida/nula
  ask                     — consulta en lenguaje natural sobre los partidos de hoy
  preview                 — avance de los partidos de mañana
"""
import asyncio
import json as _json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime as _dt
from pathlib import Path

from .config import config
from .analyzer import BetAnalysis

_DATA_REPO = Path(__file__).parent.parent


# ── display helpers ───────────────────────────────────────────────────────────

def _print_header():
    print("\n" + "=" * 60)
    print("   TONYBET BETTING ADVISOR  (powered by Claude AI)")
    print("=" * 60)


def _format_datetime(raw: str) -> str:
    if not raw:
        return "Hora desconocida"
    try:
        dt = _dt.fromisoformat(raw.replace("Z", "+00:00").replace("+00:00", ""))
        return dt.strftime("%d/%m/%Y  %H:%M")
    except Exception:
        return raw


def _market_navigation(market: str, selection: str) -> str:
    m = market.lower()

    if any(k in m for k in ("total", "over", "under", "goles", "puntos")):
        line = selection.replace("Over ", "Más de ").replace("Under ", "Menos de ")
        return (
            f"1) Busca el partido → entra al partido\n"
            f"      2) Pestaña 'GOLES' o 'TOTALES'\n"
            f"      3) Selecciona '{line}'"
        )
    if any(k in m for k in ("ambos", "btts", "marcan")):
        return (
            f"1) Busca el partido → entra al partido\n"
            f"      2) Pestaña 'PRINCIPAL' o 'MÁS APUESTAS'\n"
            f"      3) Busca 'Ambos equipos marcan' → selecciona '{selection}'"
        )
    if any(k in m for k in ("doble", "double")):
        return (
            f"1) Busca el partido → entra al partido\n"
            f"      2) Pestaña 'PRINCIPAL'\n"
            f"      3) Busca 'Doble oportunidad' → selecciona '{selection}'"
        )
    if "handicap" in m or "hándicap" in m or "spread" in m:
        return (
            f"1) Busca el partido → entra al partido\n"
            f"      2) Pestaña 'HÁNDICAP'\n"
            f"      3) Selecciona '{selection}'"
        )
    if "1x2" in m or "resultado" in m:
        return (
            f"1) Busca el partido en la lista\n"
            f"      2) Las cuotas 1-X-2 aparecen directamente\n"
            f"      3) Pulsa la cuota de '{selection}'"
        )
    if any(k in m for k in ("ganador", "winner", "moneyline")):
        return (
            f"1) Busca el partido → entra al partido\n"
            f"      2) Pestaña 'PRINCIPAL'\n"
            f"      3) 'Ganador' → selecciona '{selection}'"
        )
    return (
        f"1) Busca el partido en Tonybet\n"
        f"      2) Entra al partido → busca el mercado '{market}'\n"
        f"      3) Selecciona '{selection}'"
    )


def _print_recommendations(bets: list[BetAnalysis]):
    if not bets:
        print("\n  No se encontraron value bets en este momento.\n")
        return

    print(f"\n{'='*60}")
    print(f"  APUESTAS DEL DIA: {len(bets)} recomendaciones")
    print(f"{'='*60}")

    for i, b in enumerate(bets, 1):
        ev_pct   = b.expected_value * 100
        over_pct = b.overround * 100
        nav      = _market_navigation(b.market, b.selection)
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
    print("¿Qué apuestas quieres colocar? (números separados por coma, 'all' o 'none')")
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
    return [
        {
            "id": "1", "name": "Real Madrid vs Barcelona",
            "sport": "Fútbol", "competition": "La Liga",
            "starts_at": "2025-06-01T20:00:00",
            "markets": [
                {"name": "1X2", "selections": [
                    {"name": "Real Madrid", "odds": 2.10},
                    {"name": "Empate", "odds": 3.40},
                    {"name": "Barcelona", "odds": 3.60},
                ]},
                {"name": "Totales", "selections": [
                    {"name": "Over 2.5", "odds": 1.80},
                    {"name": "Under 2.5", "odds": 2.00},
                ]},
            ],
        },
        {
            "id": "2", "name": "Manchester City vs Arsenal",
            "sport": "Fútbol", "competition": "Premier League",
            "starts_at": "2025-06-02T17:30:00",
            "markets": [
                {"name": "1X2", "selections": [
                    {"name": "Man City", "odds": 1.85},
                    {"name": "Empate", "odds": 3.60},
                    {"name": "Arsenal", "odds": 4.20},
                ]},
            ],
        },
        {
            "id": "3", "name": "Novak Djokovic vs Carlos Alcaraz",
            "sport": "Tenis", "competition": "Roland Garros ATP",
            "starts_at": "2025-06-03T14:00:00",
            "markets": [
                {"name": "Ganador", "selections": [
                    {"name": "Djokovic", "odds": 2.30},
                    {"name": "Alcaraz", "odds": 1.65},
                ]},
            ],
        },
        {
            "id": "4", "name": "Golden State Warriors vs Boston Celtics",
            "sport": "Baloncesto", "competition": "NBA",
            "starts_at": "2025-06-03T02:00:00",
            "markets": [
                {"name": "Ganador", "selections": [
                    {"name": "Golden State Warriors", "odds": 2.10},
                    {"name": "Boston Celtics", "odds": 1.75},
                ]},
                {"name": "Totales", "selections": [
                    {"name": "Over 215.5", "odds": 1.90},
                    {"name": "Under 215.5", "odds": 1.90},
                ]},
            ],
        },
    ]


# ── event selection: sample fairly across all sports ──────────────────────────

def _select_events(events: list[dict], max_total: int = 40) -> list[dict]:
    """
    Selecciona hasta max_total eventos repartidos equilibradamente entre deportes.
    Dentro de cada deporte, prioriza las competiciones más importantes.
    """
    # Competiciones de alta prioridad por deporte
    TOP_COMPS: dict[str, list[str]] = {
        "Fútbol": [
            "premier league", "la liga", "bundesliga", "serie a", "ligue 1",
            "champions league", "europa league", "eredivisie", "primera división",
            "segunda división", "championship", "primeira liga", "süper lig",
        ],
        "Tenis": [
            "roland garros", "wimbledon", "us open", "australian open",
            "atp", "wta",
        ],
        "Baloncesto": ["nba", "euroliga", "ncaa"],
        "Hockey hielo": ["nhl", "khl", "shl"],
        "Béisbol": ["mlb"],
        "Fútbol americano": ["nfl", "ncaa"],
    }

    def _priority(e: dict) -> int:
        sport = (e.get("sport") or "").lower()
        comp  = (e.get("competition") or "").lower()
        for sp, keywords in TOP_COMPS.items():
            if sp.lower() in sport:
                if any(k in comp for k in keywords):
                    return 0
                return 1
        return 2  # otros deportes: siempre incluir

    # Agrupar por deporte
    by_sport: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        by_sport[(e.get("sport") or "Otros")].append(e)

    # Ordenar eventos dentro de cada deporte por prioridad
    sorted_by_sport: dict[str, list[dict]] = {
        sp: sorted(evts, key=_priority)
        for sp, evts in by_sport.items()
    }

    # Distribución round-robin: cada deporte aporta al menos 1 evento
    # hasta llegar a max_total, rotando por todos los deportes
    selected: list[dict] = []
    sport_iters = {sp: iter(evts) for sp, evts in sorted_by_sport.items()}
    sport_keys  = sorted(sport_iters.keys())

    while len(selected) < max_total:
        added = 0
        for sp in sport_keys:
            if len(selected) >= max_total:
                break
            try:
                selected.append(next(sport_iters[sp]))
                added += 1
            except StopIteration:
                pass
        if added == 0:
            break

    sports_repr = {e.get("sport") for e in selected}
    print(f"  Eventos seleccionados: {len(selected)}/{len(events)} de {len(by_sport)} deportes")
    print(f"  Deportes: {', '.join(sorted(sports_repr))}")
    return selected


# ── git push helper ───────────────────────────────────────────────────────────

def _git_push(*files: str, message: str) -> None:
    try:
        subprocess.run(["git", "add", *files], cwd=str(_DATA_REPO), check=True)
        subprocess.run(["git", "commit", "-m", message], cwd=str(_DATA_REPO), check=True)
        subprocess.run(["git", "push"], cwd=str(_DATA_REPO), check=True)
        print("  Dashboard actualizado en GitHub.")
    except Exception as e:
        print(f"  No se pudo publicar en GitHub: {e}")


# ── ask (consulta en lenguaje natural) ───────────────────────────────────────

async def _run_ask(question: str):
    print(f"\n  Pregunta: {question}")

    # Cargar snapshot de eventos si existe
    ev_file = _DATA_REPO / "events_latest.json"
    if ev_file.exists():
        snap = _json.loads(ev_file.read_text(encoding="utf-8"))
        events = snap.get("events", [])
        print(f"  Usando snapshot local: {len(events)} eventos")
    else:
        print("  Sin snapshot — scrapeando Tonybet…")
        from .odds_api_fetcher import fetch_events
        raw_events = fetch_events(config.odds_api_key, config.odds_api_max_requests)
        events = [
            {
                "nombre":      e.get("name"),
                "deporte":     e.get("sport"),
                "competicion": e.get("competition"),
                "hora":        e.get("starts_at"),
                "mercados":    e.get("markets", [])[:3],
            }
            for e in raw_events
        ]

    if not events:
        print("No hay eventos disponibles. Ejecuta el advisor primero.")
        return

    import anthropic
    events_json = _json.dumps(events, ensure_ascii=False, indent=2)
    prompt = (
        f"Eres un asistente experto en apuestas deportivas. El usuario pregunta:\n\n"
        f"  \"{question}\"\n\n"
        f"Responde usando únicamente los datos de los eventos disponibles a continuación. "
        f"Sé concreto, claro y organizado. Incluye cuotas cuando las haya. "
        f"Si no hay eventos que coincidan, dilo claramente.\n\n"
        f"DATOS ({len(events)} eventos):\n{events_json}"
    )

    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
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


# ── preview (avance de mañana) ────────────────────────────────────────────────

async def _run_preview(events: list[dict] | None = None):
    from datetime import timedelta
    from .form_fetcher import fetch_event_context

    tomorrow = (_dt.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"\n  Buscando partidos del {tomorrow}…\n")

    if events is None:
        from .odds_api_fetcher import fetch_events
        events = fetch_events(config.odds_api_key, config.odds_api_max_requests)

    tomorrow_events = [
        e for e in events
        if str(e.get("starts_at", "")).startswith(tomorrow)
    ]

    if not tomorrow_events:
        print(f"  No hay eventos para el {tomorrow} todavía.")
        return

    print(f"  {len(tomorrow_events)} eventos encontrados para mañana.\n")
    sample = _select_events(tomorrow_events, max_total=30)

    print("  Obteniendo datos ESPN para equipos…")
    enriched = []
    for e in sample:
        ctx = fetch_event_context(e.get("name", ""), e.get("sport", ""))
        entry = {
            "name":        e.get("name"),
            "sport":       e.get("sport"),
            "competition": e.get("competition"),
            "starts_at":   e.get("starts_at"),
            "markets":     e.get("markets", [])[:3],
        }
        if ctx:
            entry["datos_espn"] = ctx
        enriched.append(entry)

    events_json = _json.dumps(enriched, ensure_ascii=False, indent=2)

    import anthropic
    client = anthropic.Anthropic(api_key=config.anthropic_api_key)

    prompt = (
        "Eres un scout de apuestas deportivas multideporte. Tu tarea es hacer un AVANCE de los partidos de MAÑANA "
        "en TODOS los deportes disponibles.\n\n"
        "Para cada evento:\n"
        "1. Nivel de interés: ALTO / MEDIO / BAJO\n"
        "2. Qué selección/mercado podría tener valor\n"
        "3. Razón en 1-2 líneas (usa datos ESPN si están disponibles; si no, tu conocimiento)\n"
        "4. Qué información adicional cambiaría el análisis (lesiones, contexto, etc.)\n\n"
        "Al final, haz un TOP-5 de partidos más prometedores para el análisis completo de mañana.\n\n"
        "Sé directo y breve. Organiza por deporte. Formato simple.\n\n"
        f"EVENTOS DE MAÑANA ({tomorrow}):\n{events_json}"
    )

    print("  Analizando con Claude…\n")
    response = anthropic.Anthropic(api_key=config.anthropic_api_key).messages.create(
        model=config.claude_model,
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}],
    )
    analysis_text = response.content[0].text
    print(analysis_text)
    print(f"\n  ({len(sample)} eventos analizados de {len(tomorrow_events)} disponibles para mañana)")

    preview_data = {
        "updated_at":    _dt.now().strftime("%d/%m/%Y %H:%M"),
        "for_date":      tomorrow,
        "analysis":      analysis_text,
        "total_events":  len(tomorrow_events),
        "analyzed_count": len(sample),
    }
    (_DATA_REPO / "preview_latest.json").write_text(
        _json.dumps(preview_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        _git_push("preview_latest.json", message="advisor: update preview")
    except Exception:
        pass


# ── main advisor flow ─────────────────────────────────────────────────────────

async def run(mode: str = "advisor"):
    _print_header()

    try:
        if mode != "demo":
            config.validate()
    except ValueError as e:
        print(f"\n  Configuracion incompleta: {e}")
        print("   Crea un archivo .env con las variables requeridas\n")
        sys.exit(1)

    bankroll = float(os.getenv("BANKROLL", "200"))

    if mode == "preview":
        await _run_preview()
        return

    # ── 1. Obtener eventos ────────────────────────────────────────────────────
    if mode == "demo":
        print("\n[MODO DEMO] Usando eventos de ejemplo…")
        events = _load_demo_events()
    else:
        # Fuente primaria: The Odds API (fiable, 40+ deportes)
        events = []
        if config.odds_api_key:
            from .odds_api_fetcher import fetch_events
            events = fetch_events(config.odds_api_key, config.odds_api_max_requests)

        # Fallback: scraper Playwright (si no hay ODDS_API_KEY)
        if not events:
            if config.odds_api_key:
                print("  ⚠ The Odds API no devolvió eventos — probando scraper Playwright…")
            else:
                print("  ⚠ ODDS_API_KEY no configurada — usando scraper Playwright…")
            from .scraper import TonybetScraper
            scraper = TonybetScraper()
            events = await scraper.scrape()

    if not events:
        print("⚠ No se obtuvieron eventos.")
        print("  Soluciones:")
        print("  1. Configura ODDS_API_KEY (registro gratuito en https://the-odds-api.com/)")
        print("  2. Verifica las credenciales de Tonybet en TONYBET_USERNAME / TONYBET_PASSWORD")
        # Publicar estado vacío para que el dashboard muestre "sin datos"
        empty = {
            "updated_at": _dt.now().strftime("%d/%m/%Y %H:%M"),
            "total": 0,
            "events": [],
            "error": "No se pudieron obtener eventos",
        }
        (_DATA_REPO / "events_latest.json").write_text(
            _json.dumps(empty, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        try:
            _git_push("events_latest.json", message="advisor: sin eventos")
        except Exception:
            pass
        sys.exit(0)

    # ── 2. Seleccionar muestra equilibrada entre deportes ─────────────────────
    filtered = _select_events(events, max_total=60)

    # ── 3. Analizar con Claude ────────────────────────────────────────────────
    from .claude_agent import BettingAdvisor
    advisor = BettingAdvisor(bankroll=bankroll)
    value_bets = advisor.analyse(filtered)

    # ── 4. Mostrar resultados ─────────────────────────────────────────────────
    _print_recommendations(value_bets)

    if mode == "demo":
        return

    # ── 5. Guardar y publicar ─────────────────────────────────────────────────
    from .tracker import record_bets, save_latest_recommendations
    save_latest_recommendations(value_bets)
    if value_bets:
        record_bets(value_bets)

    # Snapshot de todos los eventos para el tab "Consultar" del dashboard
    compact_events = [
        {
            "nombre":      e.get("name"),
            "deporte":     e.get("sport"),
            "competicion": e.get("competition"),
            "hora":        e.get("starts_at"),
            "bookmaker":   e.get("bookmaker", ""),
            "mercados": [
                {
                    "mercado": m.get("name"),
                    "selecciones": [
                        {"nombre": s.get("name"), "cuota": s.get("odds")}
                        for s in m.get("selections", [])
                    ],
                }
                for m in e.get("markets", [])[:4]
            ],
        }
        for e in events
    ]
    events_snap = {
        "updated_at": _dt.now().strftime("%d/%m/%Y %H:%M"),
        "total":      len(compact_events),
        "events":     compact_events,
    }
    (_DATA_REPO / "events_latest.json").write_text(
        _json.dumps(events_snap, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    files_to_push = ["recommendations_latest.json", "bets_log.json", "events_latest.json"]
    _git_push(*files_to_push, message="advisor: update recommendations")

    # Generar preview de mañana automáticamente tras cada ejecución
    print("\n  Generando preview de mañana…")
    try:
        await _run_preview(events)
    except Exception as e:
        print(f"  No se pudo generar el preview: {e}")

    if not value_bets:
        return

    # ── 6. Ejecución de apuestas (solo en modo autobet/dryrun) ────────────────
    if mode not in ("autobet", "dryrun"):
        return

    selected = _ask_confirmation(value_bets)
    if not selected:
        print("Sin apuestas seleccionadas. Saliendo.")
        return

    total = sum(b.recommended_stake for b in selected)
    if total > config.max_daily_stake:
        print(f"\n  Stake total ({total:.2f}€) supera el límite diario ({config.max_daily_stake:.2f}€).")
        return

    from .bet_executor import BetExecutor
    executor = BetExecutor()

    if mode == "dryrun":
        print("\n[SIMULACION] Verificando en Tonybet… (sin confirmar apuestas)")
        placed = await executor.place_bets(selected, dry_run=True)
        print(f"\n  Simulación: {len(placed)}/{len(selected)} apuestas localizadas.")
        return

    print("\n¿Realizar apuestas REALES? Escribe 'CONFIRMAR' para proceder:")
    if input("  > ").strip() != "CONFIRMAR":
        print("Apuestas canceladas.")
        return

    placed = await executor.place_bets(selected, dry_run=False)
    print(f"\n  {len(placed)}/{len(selected)} apuestas colocadas.")


# ── entrypoint ────────────────────────────────────────────────────────────────

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "advisor"

    if mode == "stats":
        from .tracker import print_stats
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        print_stats(days)
        return

    if mode == "result":
        if len(sys.argv) < 5:
            print("Uso: python -m tonybet_advisor result \"<evento>\" \"<selección>\" <won|lost|void>")
            sys.exit(1)
        from .tracker import update_result
        update_result(sys.argv[2], sys.argv[3], sys.argv[4])
        return

    if mode == "ask":
        if len(sys.argv) < 3:
            print("Uso: python -m tonybet_advisor ask \"tu pregunta\"")
            sys.exit(1)
        asyncio.run(_run_ask(" ".join(sys.argv[2:])))
        return

    valid_modes = ("advisor", "autobet", "dryrun", "preview", "demo")
    if mode not in valid_modes:
        print(f"Uso: python -m tonybet_advisor [{'|'.join(valid_modes)}|ask|stats|result]")
        sys.exit(1)

    asyncio.run(run(mode))


if __name__ == "__main__":
    main()

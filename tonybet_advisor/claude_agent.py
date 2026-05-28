"""
Claude AI agent: analyses scraped Tonybet events and returns
structured bet recommendations using tool-use.
"""
import json

import anthropic

from .analyzer import analyse_bet, BetAnalysis
from .config import config
from .form_fetcher import fetch_event_context


# ── tool schema ───────────────────────────────────────────────────────────────

EVALUATE_BET_TOOL = {
    "name": "evaluate_bet",
    "description": (
        "Evaluate a specific betting selection. "
        "Call this for every selection you consider worth analysing. "
        "Provide your estimated true win probability based on your football/sports knowledge."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "event": {"type": "string", "description": "Event name (e.g. Real Madrid vs Barcelona)"},
            "sport": {"type": "string"},
            "market": {"type": "string", "description": "Market name (e.g. 1X2, Over/Under 2.5)"},
            "selection": {"type": "string", "description": "The chosen outcome (e.g. Home, Over)"},
            "odds": {"type": "number", "description": "Decimal odds offered by Tonybet"},
            "all_market_odds": {
                "type": "array",
                "items": {"type": "number"},
                "description": "All decimal odds in this market (for overround calculation)",
            },
            "estimated_probability": {
                "type": "number",
                "description": "Your estimated true probability (0–1) for this selection winning",
            },
            "reasoning": {
                "type": "string",
                "description": "Brief reasoning for your probability estimate",
            },
            "starts_at": {
                "type": "string",
                "description": "Match start time exactly as given in the event data (e.g. '2025-06-01T20:00:00')",
            },
        },
        "required": [
            "event", "sport", "market", "selection",
            "odds", "all_market_odds", "estimated_probability", "reasoning",
            "starts_at",
        ],
    },
}


# ── agent ─────────────────────────────────────────────────────────────────────

class BettingAdvisor:
    def __init__(self, bankroll: float = 200.0):
        self.client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self.bankroll = bankroll
        self.results: list[BetAnalysis] = []

    def _build_prompt(self, events: list[dict]) -> str:
        print("  Obteniendo datos de equipos desde ESPN…")
        sample = []
        for e in events:
            name  = e.get("name", "")
            sport = e.get("sport", "")
            ctx   = fetch_event_context(name, sport)
            entry = {
                "name":        name,
                "sport":       sport,
                "competition": e.get("competition"),
                "starts_at":   e.get("starts_at"),
                "bookmaker":   e.get("bookmaker", ""),
                "markets":     e.get("markets", []),   # todos los mercados disponibles
            }
            if ctx:
                entry["datos_espn"] = ctx
            sample.append(entry)
        events_json = json.dumps(sample, ensure_ascii=False, indent=2)

        return (
            "Eres un analista cuantitativo de apuestas deportivas MULTIDEPORTE.\n\n"

            "MISIÓN PRINCIPAL: Para CADA evento, analiza TODOS los mercados disponibles "
            "(ganador, Over/Under, BTTS, hándicap, total juegos, spread...) y llama al "
            "tool evaluate_bet por CADA selección donde los datos estadísticos justifiquen una probabilidad "
            "superior a la implícita en las cuotas. El mercado GANADOR es solo UNO de los mercados — "
            "Over/Under y BTTS son igualmente o MÁS importantes.\n\n"

            "Las cuotas provienen de Pinnacle/Betfair (referencia de mercado). "
            "El usuario apostará en Tonybet. Usa los datos estadísticos proporcionados "
            "para calcular probabilidades reales, no intuición.\n\n"

            "══════════════════════════════════════════════════════════════════\n"
            "  METODOLOGÍA DE ANÁLISIS (aplica en este orden para cada evento)\n"
            "══════════════════════════════════════════════════════════════════\n\n"

            "PASO 1 — LEE LOS DATOS ESTADÍSTICOS\n"
            "Para cada equipo/jugador busca en datos_espn:\n"
            "  • GF/pj y GC/pj (goles marcados y encajados por partido)\n"
            "  • Over 2.5 %: % de sus partidos con más de 2.5 goles totales\n"
            "  • BTTS %: % de partidos donde marcaron ambos equipos\n"
            "  • CS %: % de partidas con portería a cero\n"
            "  • Sin marcar %: % de partidas donde no marcaron\n"
            "  • Splits casa/fuera: distintos rendimientos local/visitante\n"
            "  • H2H: goles medios en enfrentamientos directos, % Over, % BTTS\n"
            "  • Ranking/forma reciente (tenis)\n"
            "  • Puntos/partido, ritmo, rating ofensivo/defensivo (basket)\n"
            "  • ERA pitcher, batting avg (béisbol)\n\n"

            "PASO 2 — CALCULA GOLES/PUNTOS ESPERADOS\n"
            "Para FÚTBOL: goles_esperados = (GF_local/pj + GC_visitante/pj + GF_visitante/pj + GC_local/pj) / 2\n"
            "EJEMPLOS con datos reales:\n"
            "  • Local GF:1.8/pj GC:1.1/pj + Visit. GF:1.4/pj GC:1.5/pj → (1.8+1.5+1.4+1.1)/2 = 2.9 goles\n"
            "    → prob Over 2.5 ≈ 60%  → prob BTTS ≈ 65% si ambos GF>1.0\n"
            "  • Local GF:0.8/pj GC:0.6/pj + Visit. GF:0.7/pj GC:0.8/pj → (0.8+0.8+0.7+0.6)/2 = 1.45 goles\n"
            "    → prob Under 2.5 ≈ 75% → prob BTTS No ≈ 60%\n\n"

            "PASO 3 — CONFIRMA CON HISTORIAL\n"
            "Si los datos ESPN dan Over 2.5 = 72% en casa y el H2H muestra 4/5 partidos Over → prob real ≈ 68-72%\n"
            "El historial directo (H2H) tiene más peso que las estadísticas generales.\n\n"

            "PASO 4 — COMPARA CON CUOTA IMPLÍCITA\n"
            "Cuota 1.80 → implícita 55.6%. Si tu prob real es 62% → EV = 62%*0.80 - 38% = +11.6% → ¡EXCELENTE!\n"
            "Cuota 1.90 → implícita 52.6%. Si tu prob real es 57% → EV = 57%*0.90 - 43% = +8.3% → BUENA apuesta\n\n"

            "PASO 5 — LLAMA AL TOOL\n"
            "Si prob_estimada > prob_implícita + 2% → llama evaluate_bet\n"
            "No esperes certeza absoluta. En apuestas deportivas, 58% vs 52% implícita ES valor.\n\n"

            "══════════════════════════════════════════════════════════════════\n"
            "  MERCADOS A ANALIZAR EN CADA ENCUENTRO (PRIORIDAD DESCENDENTE)\n"
            "══════════════════════════════════════════════════════════════════\n\n"

            "🥇 MERCADOS ESTADÍSTICOS (analiza SIEMPRE que haya datos):\n"
            "  1. Over/Under 2.5 goles (fútbol) — usa goles_esperados y % histórico Over\n"
            "  2. BTTS Sí/No — usa GF/pj y GC/pj de ambos + % BTTS histórico\n"
            "  3. Over/Under 3.5 goles — cuando goles_esperados > 3.2\n"
            "  4. Total puntos/juegos (basket, tenis, hockey) — usa puntos/partido histórico\n"
            "  5. Hándicap/Spread — cuando hay diferencia clara de nivel\n\n"

            "🥈 MERCADO GANADOR (analiza cuando hay ventaja clara):\n"
            "  6. 1X2 / Ganador — solo cuando la diferencia estadística es suficiente\n\n"

            "══════════════════════════════════════════════════════════════════\n"
            "  FÚTBOL — GUÍA DE CÁLCULO DETALLADA\n"
            "══════════════════════════════════════════════════════════════════\n\n"

            "OVER/UNDER GOLES:\n"
            "  goles_esp = (GF_L/pj + GC_V/pj + GF_V/pj + GC_L/pj) / 2\n"
            "  Ajuste por splits casa/fuera (usa stats de casa para local, fuera para visitante)\n"
            "  Ajuste por H2H: si H2H medio_goles > goles_esp → +0.2 goles\n"
            "  Over 2.5 base prob:\n"
            "    goles_esp < 1.8 → ~20%  | 1.8-2.2 → ~38% | 2.2-2.6 → ~52%\n"
            "    2.6-3.0 → ~62% | 3.0-3.5 → ~70% | > 3.5 → ~78%\n"
            "  Refuerzo: si ambos equipos tienen Over 2.5 > 60% históricamente → +5%\n"
            "  Under 2.5 = 1 - prob_Over_2.5 (ajusta por vigor de mercado)\n\n"

            "BTTS (ambos marcan):\n"
            "  Señal positiva: GF_L/pj > 1.0 Y GF_V/pj > 0.9 Y GC_L/pj > 0.7 Y GC_V/pj > 0.8\n"
            "  Señal negativa: GC de cualquiera < 0.6 (portería sólida) O GF < 0.7 (ataque pobre)\n"
            "  Base prob BTTS Sí: usa el % BTTS histórico de ambos equipos → media ponderada\n"
            "  Ejemplo: Local BTTS% en casa = 65%, Visitante BTTS% fuera = 58% → prob ≈ 61%\n\n"

            "1X2:\n"
            "  Usa record en casa (local) y fuera (visitante), forma ult.5, posición, GF/GC\n"
            "  Factor sorpresa mínimo: si local es ≥5 posiciones mejor + mejor forma → 60%+\n"
            "  Doble oportunidad 1X: si local es favorito ligero (odds > 2.20) → 70%+ factible\n\n"

            "HÁNDICAP:\n"
            "  Usa diferencia de GF/pj entre equipos y forma reciente\n"
            "  Hándicap -1: local ganó por 2+ en 40%+ de sus últimos partidos → evalúa\n\n"

            "══════════════════════════════════════════════════════════════════\n"
            "  TENIS\n"
            "══════════════════════════════════════════════════════════════════\n\n"

            "GANADOR: diferencia ranking + especialidad de superficie\n"
            "  Tierra batida: Alcaraz, Nadal, Djokovic, Tsitsipas, Cerúndolo dominan\n"
            "  Diff ranking > 30 en tierra con especialista → 68%+\n"
            "  Diff ranking > 25 en pista dura → 65%+\n\n"

            "TOTAL JUEGOS (Over/Under 22.5, 23.5...):\n"
            "  Favorito muy claro (>80%) + rival débil → Under juegos probable (~62%)\n"
            "  Dos jugadores equilibrados (odds 1.65-2.10 ambos) → Over juegos (~60%)\n"
            "  Usa el número de sets esperados: mejor-de-3 con barrido 2-0 probable → Under\n\n"

            "══════════════════════════════════════════════════════════════════\n"
            "  BALONCESTO\n"
            "══════════════════════════════════════════════════════════════════\n\n"

            "TOTAL PUNTOS — mercado más predecible:\n"
            "  puntos_esp = (PPG_local + PPG_visitante + PAPG_local + PAPG_visitante) / 2\n"
            "  donde PPG = puntos anotados/partido, PAPG = puntos encajados/partido\n"
            "  Resultado > 5pts sobre la línea → prob >62% al lado correcto\n"
            "  Back-to-back: resta 4-6 puntos al total esperado\n\n"

            "HÁNDICAP PUNTOS:\n"
            "  Favorito debe cubrir el spread. Solo cuando diferencia de nivel > 10 victorias\n"
            "  y el favorito está en casa sin back-to-back\n\n"

            "══════════════════════════════════════════════════════════════════\n"
            "  HOCKEY, BÉISBOL, NFL, MMA, RUGBY\n"
            "══════════════════════════════════════════════════════════════════\n\n"

            "HOCKEY — Total goles (Over/Under 5.5, 6.5...):\n"
            "  Equipos con >3.2 goles/partido promedio de ambos → Over 5.5 ~60%\n"
            "  Save% > 0.920 para portero titular → favorece Under\n\n"

            "BÉISBOL — Total carreras (Over/Under 8.5, 9.5...):\n"
            "  ERA pitcher < 3.00 + rival con bajo batting avg → Under carreras ~60%\n"
            "  Estadio Coors Field (Colorado) → siempre sesga Over\n\n"

            "NFL — Spread y totales:\n"
            "  Home field ≈ 3 puntos ventaja. QB ausente = equipo pierde 7-10 puntos de valor\n"
            "  Clima viento > 20mph → Under puntos muy probable (~65%)\n\n"

            "MMA/BOXEO — Ganador:\n"
            "  Compatibilidad de estilos: grappler vs striker sin suelo = grappler gana ~65%\n"
            "  Cuota 1.40-1.80 con dominancia técnica clara → EV factible\n\n"

            "══════════════════════════════════════════════════════════════════\n"
            "  UMBRALES MÍNIMOS Y CUOTAS VÁLIDAS\n"
            "══════════════════════════════════════════════════════════════════\n\n"

            "CUOTAS VÁLIDAS: 1.15 – 8.00\n\n"

            "UMBRAL MÍNIMO por mercado (prob_estimada > implícita + este margen):\n"
            "╔══════════════════════╦════════╦══════════════════════════════════╗\n"
            "║ Mercado              ║ Mínimo ║ Ejemplo de valor                 ║\n"
            "╠══════════════════════╬════════╬══════════════════════════════════╣\n"
            "║ Fútbol Over/Under    ║  57%   ║ Over 2.5 @1.80 con goles_esp 3.0 ║\n"
            "║ Fútbol BTTS Sí/No    ║  55%   ║ BTTS Sí @1.85 con ambos GF>1.1  ║\n"
            "║ Fútbol 1X2           ║  62%   ║ Local @1.70 con clara ventaja    ║\n"
            "║ Fútbol Hándicap      ║  60%   ║ -1 @2.00 con GF 2.0 vs 0.8      ║\n"
            "║ Tenis Ganador        ║  65%   ║ Rank #10 vs #55 tierra           ║\n"
            "║ Tenis Total juegos   ║  55%   ║ Under 21.5 con favorito claro    ║\n"
            "║ Basket Total puntos  ║  57%   ║ Over 220 con dos equipos >110ppg ║\n"
            "║ Basket Ganador       ║  63%   ║ Local con +12 victorias ventaja  ║\n"
            "║ Hockey Total goles   ║  57%   ║ Over 5.5 con ambos >3.0 goles/pj ║\n"
            "║ Hockey Ganador       ║  60%   ║ Local top vs visitante colista   ║\n"
            "║ Béisbol Total        ║  57%   ║ Under con ERA < 3.0 ambos        ║\n"
            "║ NFL Spread           ║  58%   ║ Favorito -3.5 en casa            ║\n"
            "║ MMA/Boxeo Ganador    ║  65%   ║ Estilo claramente ventajoso      ║\n"
            "║ Rugby Ganador        ║  62%   ║ Top vs colista en casa           ║\n"
            "╚══════════════════════╩════════╩══════════════════════════════════╝\n\n"

            "OBJETIVO DE SESIÓN: 8-15 apuestas de valor. Con 50-60 eventos multideporte "
            "y múltiples mercados por evento, siempre hay apuestas con valor estadístico.\n\n"

            f"Bankroll: {self.bankroll}€\n\n"

            "EVENTOS (con estadísticas ESPN donde disponibles):\n"
            f"{events_json}"
        )

    def _handle_tool_call(self, tool_input: dict) -> BetAnalysis:
        return analyse_bet(
            event=tool_input["event"],
            sport=tool_input["sport"],
            market=tool_input["market"],
            selection=tool_input["selection"],
            odds=tool_input["odds"],
            market_odds=tool_input["all_market_odds"],
            estimated_prob=tool_input["estimated_probability"],
            bankroll=self.bankroll,
            kelly_fraction=config.kelly_fraction,
            min_ev=config.min_ev_threshold,
            max_stake=config.max_single_bet,
            starts_at=tool_input.get("starts_at", ""),
        )

    def analyse(self, events: list[dict]) -> list[BetAnalysis]:
        if not events:
            print("No hay eventos para analizar.")
            return []

        print(f"\nAnalizando {len(events)} eventos con Claude…")
        self.results = []

        messages = [{"role": "user", "content": self._build_prompt(events)}]

        # Agentic loop: Claude may call evaluate_bet multiple times
        while True:
            import time
            for attempt in range(3):
                try:
                    response = self.client.messages.create(
                        model=config.claude_model,
                        max_tokens=8192,
                        tools=[EVALUATE_BET_TOOL],
                        messages=messages,
                    )
                    break
                except Exception as e:
                    if "rate_limit" in str(e).lower() and attempt < 2:
                        wait = 65 * (attempt + 1)
                        print(f"  Rate limit alcanzado, esperando {wait}s...")
                        time.sleep(wait)
                    else:
                        raise

            # Collect any text output
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    print(f"\n💬 Claude: {block.text}\n")

            if response.stop_reason == "end_turn":
                break

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    analysis = self._handle_tool_call(block.input)
                    self.results.append(analysis)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps({
                            "ev": analysis.expected_value,
                            "kelly": analysis.kelly_fraction,
                            "stake": analysis.recommended_stake,
                            "is_value": analysis.is_value_bet,
                            "overround": analysis.overround,
                        }),
                    })

                # Feed results back to Claude
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
            else:
                break

        value_bets = [r for r in self.results if r.is_value_bet]
        value_bets = value_bets[:15]  # máximo 15 apuestas por sesión
        print(f"✓ Análisis completado: {len(value_bets)} value bets encontradas")
        return value_bets

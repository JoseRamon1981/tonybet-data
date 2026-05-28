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
            "Eres un analista de apuestas deportivas MULTIDEPORTE y BUSCADOR DE VALOR.\n\n"

            "FILOSOFIA: Tu objetivo es encontrar VALOR en el mercado. El valor existe cuando "
            "tu probabilidad estimada supera la probabilidad implícita en las cuotas. "
            "Con 50-60 eventos disponibles, DEBES encontrar al menos 5-10 apuestas con valor. "
            "Si analizas 50 eventos y solo encuentras 1-2 apuestas, estás siendo demasiado conservador.\n\n"

            "Las cuotas provienen de casas de apuestas de referencia (Pinnacle, Betfair, etc.). "
            "El usuario apostará en Tonybet, que ofrece cuotas similares. Tu análisis es sobre el valor "
            "real de la selección, independientemente de la casa específica.\n\n"

            "╔═══════════════════════════════════════════════════════════╗\n"
            "║         ANÁLISIS POR DEPORTE Y MERCADO                   ║\n"
            "╚═══════════════════════════════════════════════════════════╝\n\n"

            "REGLA DE ORO: los mercados de TOTALES (Over/Under) y AMBOS MARCAN son a menudo\n"
            "MÁS FÁCILES de predecir que el ganador, porque no dependen de quién gana sino\n"
            "de cuánto se anota. ¡Analízalos SIEMPRE que estén disponibles en los datos!\n\n"

            "═══ FÚTBOL ═══════════════════════════════════════════════════\n\n"

            "DATOS ESPN disponibles: posición en tabla, record W/D/L, GF/GC, forma ult.5, "
            "splits local/visitante, H2H, lesiones.\n\n"

            "── MERCADO 1X2 (umbral mínimo: 62%) ──\n"
            "• Favorito local con ventaja clara de forma/tabla → 65%+\n"
            "• Doble oportunidad 1X (local no pierde): equipo sólido en casa → 68%+\n"
            "• Victoria visitante si hay clara diferencia de nivel → 62%+\n"
            "• EJEMPLO: equipo 3° vs equipo 16°, ambos en forma similar → local 65%\n\n"

            "── MERCADO OVER/UNDER GOLES (umbral mínimo: 57%) ── ← MERCADO PRIORITARIO\n"
            "Este mercado NO depende del ganador. Calcula así:\n"
            "  goles_esperados = (GF_local/pj + GC_local/pj + GF_visitante/pj + GC_visitante/pj) / 2\n"
            "EJEMPLOS:\n"
            "• Local GF:1.8 GC:1.2 + Visit. GF:1.5 GC:1.4 → (~3.0 goles) → Over 2.5 prob ~62% → ¡LLAMA AL TOOL!\n"
            "• Local GF:0.9 GC:0.7 + Visit. GF:0.8 GC:0.6 → (~1.5 goles) → Under 2.5 prob ~65% → ¡LLAMA AL TOOL!\n"
            "• H2H: si los últimos 5 directos promedian >2.5 goles → refuerza Over\n"
            "• SIEMPRE evalúa Over/Under cuando hay datos de GF/GC disponibles\n\n"

            "── MERCADO AMBOS MARCAN / BTTS (umbral mínimo: 55%) ── ← MUY RECOMENDADO\n"
            "Solo necesitas que ambos equipos marquen AL MENOS 1 gol.\n"
            "BTTS SÍ cuando: ambos con GF > 1.0/pj Y ambos con GC > 0.7/pj → ~58%+\n"
            "BTTS NO cuando: algún equipo tiene GC < 0.5/pj (defensa muy sólida) → ~60%+\n"
            "Cuotas BTTS típicas: 1.65-2.00 → con 57% de prob ya hay EV positivo con cuota 1.75\n\n"

            "── MERCADO HÁNDICAP GOLES (umbral mínimo: 60%) ──\n"
            "• Hándicap -1 al local: el local debe ganar por 2+ goles\n"
            "• Cuando hay diferencia de nivel moderada-clara entre equipos\n"
            "• Cuota del hándicap suele ser 1.85-2.10 → con 60% de prob EV ~12%\n\n"

            "SEÑALES POSITIVAS EN FÚTBOL:\n"
            "• Equipo en buena forma (3+ victorias últimas 5) vs equipo en mala forma → valor en ganador\n"
            "• Ambos equipos atacadores (GF > 1.5) → Over y BTTS con alta probabilidad\n"
            "• Defensa sólida de uno (GC < 0.8) + rival poco goleador (GF < 1.0) → Under/BTTS No\n\n"

            "═══ TENIS ════════════════════════════════════════════════════\n\n"

            "── MERCADO GANADOR (umbral mínimo: 65%) ──\n"
            "TIERRA BATIDA (Roland Garros, Madrid, Roma, Montecarlo):\n"
            "• Especialistas: Nadal, Alcaraz, Djokovic, Tsitsipas, Cerúndolo, Ruud\n"
            "• Diferencia ranking > 30 puestos Y especialista de superficie → 68%+\n"
            "• Top-20 vs fuera del top-60 → 65%+\n\n"

            "HIERBA / PISTA DURA:\n"
            "• Rankings ATP/WTA fiables en pista dura\n"
            "• Diferencia ranking > 35 puestos → 65%+\n\n"

            "── MERCADO TOTAL JUEGOS (umbral mínimo: 55%) ── ← EXPLORAR SIEMPRE\n"
            "• Favorito claro (prob >75%) + rival débil → Under juegos (partido corto) ~58%\n"
            "• Dos jugadores equilibrados de fondo de pista → Over juegos ~57%\n\n"

            "═══ BALONCESTO (NBA / EUROLIGA / NCAA) ══════════════════════\n\n"

            "── MERCADO GANADOR (umbral mínimo: 63%) ──\n"
            "• Diferencia de record > 10 victorias + local en casa → 65%+\n"
            "• Equipo con lesiones de estrella → ajusta prob del rival +8-12%\n\n"

            "── MERCADO TOTAL PUNTOS (umbral mínimo: 57%) ── ← MUY RECOMENDADO\n"
            "• Dos equipos ofensivos (>110 ppp) → Over casi seguro ~62%\n"
            "• Equipos lentos/defensivos (<105 ppp) → Under ~60%\n"
            "• Back-to-back reduce puntos ~5-8 por equipo\n\n"

            "── MERCADO HÁNDICAP PUNTOS (umbral mínimo: 60%) ──\n"
            "• Diferencia de record significativa + el mejor en casa → 62%+\n\n"

            "═══ HOCKEY HIELO (NHL / KHL / SHL) ══════════════════════════\n\n"

            "UMBRAL MÍNIMO: 60%\n\n"

            "VARIABLES CLAVE:\n"
            "• Equipos ofensivos (> 3.0 goles/partido) vs defensas blandas → Over\n"
            "• Record en casa significativo + rival de viaje → 62%+\n"
            "• Favorito con win% > 60% en casa vs equipo < 40% de visitante → 63%+\n\n"

            "═══ BÉISBOL (MLB) ════════════════════════════════════════════\n\n"

            "UMBRAL MÍNIMO: 58%\n\n"

            "VARIABLES CLAVE:\n"
            "• Pitcher abridor es LA variable más importante\n"
            "• Estadios pequeños (Coors) favorecen Over en carreras\n"
            "• Equipos con batting > 0.270 vs ERA > 4.50 → Over carreras 58%+\n\n"

            "═══ FÚTBOL AMERICANO (NFL / NCAA) ═══════════════════════════\n\n"

            "UMBRAL MÍNIMO: 62%\n\n"

            "• QB estrella en casa vs rival con QB débil → 65%+\n"
            "• NFL spread: busca equipos muy favoritos en casa cubriendo el spread\n"
            "• Clima: viento > 20mph → Under puntos 60%+\n\n"

            "═══ MMA / BOXEO ══════════════════════════════════════════════\n\n"

            "UMBRAL MÍNIMO: 65%\n\n"

            "• Dominancia técnica clara (striker superior vs rival sin defensa de suelo) → 68%+\n"
            "• Racha de victorias vs nivel similar → refuerza probabilidad\n"
            "• Cuota 1.35-1.80 con superioridad técnica clara → EV positivo factible\n\n"

            "═══ RUGBY (Union / League) ════════════════════════════════════\n\n"

            "UMBRAL MÍNIMO: 62%\n\n"

            "• Top-3 local vs bottom-3 visitante → 65%+\n"
            "• Forma reciente + ventaja de campo → 63%+\n\n"

            "═══ CRICKET ═════════════════════════════════════════════════\n\n"

            "UMBRAL MÍNIMO: 58%\n\n"

            "• Diferencia significativa de forma y composición de equipo → 60%+\n\n"

            "═══ GOLF ════════════════════════════════════════════════════\n\n"

            "UMBRAL MÍNIMO: 58% para head-to-head entre dos jugadores\n\n"

            "• Diferencia clara de forma reciente en ese circuito → 60%+\n\n"

            "═══════════════════════════════════════════════════════════════\n"
            "              CRITERIOS GLOBALES\n"
            "═══════════════════════════════════════════════════════════════\n\n"

            "CUOTAS VÁLIDAS: 1.15 – 8.00\n"
            "• < 1.15: EV matemáticamente casi imposible → NUNCA apostar\n"
            "• > 8.00: demasiada varianza → evitar salvo casos muy claros\n\n"

            "EV MÍNIMO: +1% para recomendar\n\n"

            "MÁXIMO: 15 apuestas por sesión. Busca activamente 8-15 apuestas de valor.\n\n"

            "UMBRALES MÍNIMOS DE PROBABILIDAD (son MÍNIMOS, no objetivos):\n"
            "╔══════════════════════════╦════════╦══════════════════════════════╗\n"
            "║ Mercado                  ║ Mínimo ║ Cuota típica → EV con mínimo ║\n"
            "╠══════════════════════════╬════════╬══════════════════════════════╣\n"
            "║ Fútbol 1X2 / Doble op.   ║  62%   ║ 1.70 → EV +5%               ║\n"
            "║ Fútbol Over/Under goles  ║  57%   ║ 1.80 → EV +3%               ║\n"
            "║ Fútbol Ambos marcan BTTS ║  55%   ║ 1.85 → EV +2%               ║\n"
            "║ Fútbol Hándicap          ║  60%   ║ 1.90 → EV +4%               ║\n"
            "║ Tenis Ganador            ║  65%   ║ 1.55 → EV +1%               ║\n"
            "║ Tenis Total juegos       ║  55%   ║ 1.85 → EV +2%               ║\n"
            "║ Basket Ganador           ║  63%   ║ 1.60 → EV +1%               ║\n"
            "║ Basket Total puntos      ║  57%   ║ 1.80 → EV +3%               ║\n"
            "║ Basket Hándicap puntos   ║  60%   ║ 1.90 → EV +4%               ║\n"
            "║ Hockey Ganador           ║  60%   ║ 1.70 → EV +2%               ║\n"
            "║ Hockey Total goles       ║  57%   ║ 1.80 → EV +3%               ║\n"
            "║ Béisbol Ganador          ║  58%   ║ 1.85 → EV +7%               ║\n"
            "║ Béisbol Total carreras   ║  57%   ║ 1.85 → EV +5%               ║\n"
            "║ NFL Ganador              ║  62%   ║ 1.65 → EV +2%               ║\n"
            "║ NFL Total puntos         ║  57%   ║ 1.85 → EV +5%               ║\n"
            "║ NFL Spread               ║  58%   ║ 1.90 → EV +10%              ║\n"
            "║ MMA/Boxeo Ganador        ║  65%   ║ 1.55 → EV +1%               ║\n"
            "║ Rugby Ganador/Hándicap   ║  62%   ║ 1.70 → EV +5%               ║\n"
            "╚══════════════════════════╩════════╩══════════════════════════════╝\n\n"

            "RECUERDA: Con 50-60 eventos de múltiples deportes, hay SIEMPRE apuestas con valor. "
            "Sé activo: analiza cada evento y llama al tool para cada selección que supere el umbral.\n\n"

            f"Bankroll: {self.bankroll}€\n\n"

            "EVENTOS (con datos ESPN donde disponibles):\n"
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
                        max_tokens=4096,
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

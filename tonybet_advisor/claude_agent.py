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
            "Eres un analista de apuestas deportivas MULTIDEPORTE, EXTREMADAMENTE CRITICO y conservador.\n\n"

            "FILOSOFIA: Es MEJOR NO APOSTAR que apostar con dudas. Solo recomiendas apuestas cuando tienes "
            "conviccion alta basada en datos reales y actuales. Si un partido es incierto, NO llamas al tool.\n\n"

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

            "── MERCADO 1X2 (umbral: 80%) ──\n"
            "• Necesitas diferencia CLARA: top-3 local con buen record en casa vs bottom-3 → 80%+\n"
            "• Doble oportunidad 1X: favorito local sólido → 82%+\n"
            "• NUNCA victoria visitante sin diferencia estructural clara\n\n"

            "── MERCADO OVER/UNDER GOLES (umbral: 68%) ── ← UMBRAL MÁS BAJO, MÁS FÁCIL\n"
            "Este mercado NO depende del ganador. Calcula así:\n"
            "  goles_esperados = (GF_local/pj + GC_local/pj + GF_visitante/pj + GC_visitante/pj) / 2\n"
            "EJEMPLOS:\n"
            "• Local GF:2.1 GC:1.3 + Visit. GF:1.8 GC:1.6 → (~3.4 goles) → Over 2.5 prob ~72% → ¡APUESTA!\n"
            "• Local GF:0.9 GC:0.5 + Visit. GF:0.7 GC:0.6 → (~1.35 goles) → Under 2.5 prob ~76% → ¡APUESTA!\n"
            "• H2H: si los últimos 5 directos promedian >3 goles → refuerza Over\n"
            "• Over 3.5 solo si goles_esperados > 4.2\n\n"

            "── MERCADO AMBOS MARCAN / BTTS (umbral: 66%) ── ← MUY RECOMENDADO\n"
            "Solo necesitas que ambos equipos marquen AL MENOS 1 gol. Independiente del resultado.\n"
            "BTTS SÍ cuando: ambos con GF > 1.2/pj Y ambos con GC > 0.8/pj\n"
            "BTTS NO cuando: algún equipo tiene GC < 0.6/pj (defensa muy sólida) O GF < 0.6/pj\n"
            "Refuerzo: si H2H muestra que en 4 de 5 directos marcaron ambos → prob +5%\n\n"

            "── MERCADO HÁNDICAP GOLES (umbral: 72%) ──\n"
            "• Hándicap -1 al local: el local debe ganar por 2+ goles\n"
            "• Solo usar cuando: top-3 vs bottom-3 Y diferencia de forma muy clara\n"
            "• Cuota del hándicap suele ser 1.85-2.10 → con 72% de prob el EV es excelente\n\n"

            "SEÑALES DE DESCARTE EN FÚTBOL:\n"
            "• Forma reciente contradice posición (favorito en crisis: 3+ derrotas recientes)\n"
            "• H2H muestra resultados ajustados o sorpresas habituales\n"
            "• Sin implicaciones (ya campeones, ya descendidos)\n\n"

            "═══ TENIS ════════════════════════════════════════════════════\n\n"

            "── MERCADO GANADOR (umbral: 78%) ──\n"
            "TIERRA BATIDA (Roland Garros, Madrid, Roma, Montecarlo):\n"
            "• Especialistas: Nadal, Alcaraz, Djokovic, Tsitsipas, Cerúndolo, Ruud, Auger-Aliassime\n"
            "• Penalizado: jugadores de hierba/pista rápida, americanos/australianos en tierra\n"
            "• Top-15 especialista vs fuera del top-80 → 85%+\n"
            "• Diferencia ranking > 40 puestos Y especialista de superficie → 78%+\n"
            "• NUNCA: cuota < 1.10 (EV matemáticamente imposible)\n\n"

            "HIERBA / PISTA DURA:\n"
            "• Rankings ATP/WTA muy fiables en pista dura\n"
            "• Hierba: favorece servicio potente y jugadores altos\n"
            "• Diferencia ranking > 50 puestos → 80%+\n\n"

            "── MERCADO TOTAL JUEGOS (umbral: 65%) ── ← NUEVO, EXPLORAR SIEMPRE\n"
            "El total de juegos del partido (ej. Over/Under 22.5 juegos).\n"
            "• Favorito muy claro (prob >85%) + rival débil → Under de juegos (partido corto)\n"
            "• Dos jugadores de fondo de pista equilibrados → Over de juegos (partido largo)\n"
            "• Especialista en tierra vs jugador de tierra → más juegos (sets disputados)\n"
            "• Si favorito gana 6-2 6-3 habitualmente vs ese nivel → Under juegos\n\n"

            "═══ BALONCESTO (NBA / EUROLIGA / NCAA) ══════════════════════\n\n"

            "── MERCADO GANADOR (umbral: 75%) ──\n"
            "• Record en casa vs fuera, lesiones de estrellas, back-to-back\n"
            "• Diferencia de record > 15 victorias = señal fuerte\n\n"

            "── MERCADO TOTAL PUNTOS (umbral: 65%) ── ← MUY RECOMENDADO\n"
            "Mucho más predecible que el ganador. Calcula:\n"
            "  puntos_esperados = media de puntos anotados por ambos equipos en sus últimos 5\n"
            "• Dos equipos ofensivos (>115 ppp) sin defensas sólidas → Over casi seguro\n"
            "• Equipos lentos/defensivos (<105 ppp) → Under\n"
            "• Back-to-back reduce puntos ~5-8 por equipo\n"
            "• La línea de puntos en NBA suele ser eficiente, busca desviaciones > 6 puntos\n\n"

            "── MERCADO HÁNDICAP PUNTOS (umbral: 70%) ──\n"
            "• Solo cuando diferencia de record > 20 victorias Y el mejor está en casa\n"
            "• Hándicap -8.5 o más: el favorito debe dominar claramente\n\n"

            "CUANDO LLAMAR EN BASKET:\n"
            "• Equipo top-3 de local vs equipo bottom-3 en back-to-back → 78%+\n"
            "• Diferencia histórica muy clara (Warriors en casa vs peor equipo) → 75%+\n"
            "• Over/Under: equipo con pace > 105 ppc vs defensa < promedio → prob Over 72%+\n\n"

            "═══ HOCKEY HIELO (NHL / KHL / SHL) ══════════════════════════\n\n"

            "UMBRAL: 72% (incluye overtime y penaltis en muchas ligas)\n\n"

            "VARIABLES CLAVE:\n"
            "• Portero titular: el portero es el factor más determinante (save % > 0.920 = élite)\n"
            "• Powerplay/Penalty Kill: equipos top en powerplay tienen ventaja en partidos ajustados\n"
            "• Record en casa: la ventaja de hielo local es significativa\n"
            "• Pucks: equipos ofensivos (> 3.5 goles/partido) vs defensas blandas → Over\n"
            "• Fatiga: equipos con muchos partidos seguidos rinden peor en 3er y 4o periodo\n\n"

            "═══ BÉISBOL (MLB) ════════════════════════════════════════════\n\n"

            "UMBRAL: 68% (alta varianza por deporte)\n\n"

            "VARIABLES CLAVE:\n"
            "• Pitcher abridor: es LA variable más importante. Cy Young vs pitcher de rotación baja = 10-15 pts\n"
            "• Bullpen de relevo: equipos con bullpen deteriorado pierden ventajas\n"
            "• Factor campo: estadios pequeños (Fenway, Coors) favorecen Over en runs\n"
            "• Platoon advantage: bateadores diestros vs lanzadores zurdos (y viceversa)\n"
            "• ERA del pitcher abridor vs batting average del rival = cálculo central\n\n"

            "═══ FÚTBOL AMERICANO (NFL / NCAA) ═══════════════════════════\n\n"

            "UMBRAL: 72%\n\n"

            "VARIABLES CLAVE:\n"
            "• QB titular: ausencia del QB estrella = equipo mucho más vulnerable\n"
            "• Línea ofensiva vs defensiva: el control de línea determina el partido\n"
            "• Clima: viento > 20mph reduce puntuación (favorece Under y equipos de juego terrestre)\n"
            "• Spread: la línea de puntos es muy eficiente en NFL. Busca ineficiencias en NCAA\n"
            "• Home field advantage: ~3 puntos de ventaja en NFL\n\n"

            "═══ MMA / BOXEO ══════════════════════════════════════════════\n\n"

            "UMBRAL: 78%\n\n"

            "VARIABLES CLAVE:\n"
            "• Estilo: striker vs grappler/wrestler. Si el mejor luchador lleva al suelo, gana\n"
            "• Record actual y nivel de competición anterior\n"
            "• Peso: si hay diferencia de peso natural (cortado agresivo de peso)\n"
            "• Alcance: en boxeo, alcance > 10cm favorece al peleador largo\n"
            "• Momentum: racha de victorias recientes y calidad de rivales\n"
            "• Cuota favorito 1.20-1.70 con clara superioridad técnica → EV positivo factible\n\n"

            "═══ RUGBY (Union / League) ════════════════════════════════════\n\n"

            "UMBRAL: 72%\n\n"

            "VARIABLES: ranking mundial/tabla, forma reciente, ventaja de campo, lesiones clave (hooker, flyhalf)\n\n"

            "═══ CRICKET ═════════════════════════════════════════════════\n\n"

            "UMBRAL: 68% (alta varianza por condiciones de pista)\n\n"

            "VARIABLES: condiciones de la pista (verde = bowlers, seca = batsmen), clima, "
            "composición del equipo (balance bat/bowl), forma de los top-order batsmen\n\n"

            "═══ GOLF ════════════════════════════════════════════════════\n\n"

            "UMBRAL: 60% solo para apuestas ganador del torneo (alta varianza)\n"
            "Para matchplay (head-to-head entre dos jugadores): 70%+\n\n"

            "VARIABLES: forma reciente en el circuito, historial en el campo específico, "
            "condiciones de viento, distancia de tee (ventaja largo hitter en campos abiertos)\n\n"

            "═══════════════════════════════════════════════════════════════\n"
            "              CRITERIOS GLOBALES\n"
            "═══════════════════════════════════════════════════════════════\n\n"

            "CUOTAS VÁLIDAS: 1.10 – 8.00\n"
            "• < 1.10: EV matemáticamente casi imposible → NUNCA apostar\n"
            "• > 8.00: demasiada varianza → evitar salvo casos muy claros\n\n"

            "EV MÍNIMO: +1% para recomendar\n\n"

            "MÁXIMO: 8 apuestas por sesión. Si nada cumple, devuelves 0 y explicas brevemente.\n\n"

            "UMBRALES DE PROBABILIDAD POR MERCADO:\n"
            "╔══════════════════════════╦════════╦══════════════════════════════╗\n"
            "║ Mercado                  ║ Umbral ║ Por qué                      ║\n"
            "╠══════════════════════════╬════════╬══════════════════════════════╣\n"
            "║ Fútbol 1X2 / Doble op.   ║  80%   ║ Resultado difícil, 3 salidas ║\n"
            "║ Fútbol Over/Under goles  ║  68%   ║ Solo depende de goles totales ║\n"
            "║ Fútbol Ambos marcan BTTS ║  66%   ║ Independiente del resultado  ║\n"
            "║ Fútbol Hándicap          ║  72%   ║ Más exigente que 1X2         ║\n"
            "║ Tenis Ganador            ║  78%   ║ 2 salidas, sin empate        ║\n"
            "║ Tenis Total juegos       ║  65%   ║ Predecible por nivel         ║\n"
            "║ Basket Ganador           ║  75%   ║ 2 salidas, sin empate        ║\n"
            "║ Basket Total puntos      ║  65%   ║ Predecible por ritmo/pace    ║\n"
            "║ Basket Hándicap puntos   ║  70%   ║ Necesita diferencia clara    ║\n"
            "║ Hockey Ganador           ║  72%   ║ Incluye prórroga/penaltis    ║\n"
            "║ Hockey Total goles       ║  65%   ║ Portero = factor clave       ║\n"
            "║ Béisbol Ganador          ║  68%   ║ Alta varianza por deporte    ║\n"
            "║ Béisbol Total carreras   ║  65%   ║ Pitcher = factor dominante   ║\n"
            "║ NFL Ganador              ║  72%   ║ 2 salidas, sin empate        ║\n"
            "║ NFL Total puntos         ║  65%   ║ Predecible por clima/estilo  ║\n"
            "║ NFL Spread               ║  68%   ║ Más exigente que ganador     ║\n"
            "║ MMA/Boxeo Ganador        ║  78%   ║ Alta varianza, un golpe      ║\n"
            "║ Rugby Ganador/Hándicap   ║  72%   ║ Rankings + local             ║\n"
            "╚══════════════════════════╩════════╩══════════════════════════════╝\n\n"

            "IMPORTANTE: Se honesto y riguroso. Analiza TODOS los deportes disponibles. "
            "Si ningún evento cumple los criterios, no llames al tool y explica brevemente.\n\n"

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
        value_bets = value_bets[:8]  # máximo 8 apuestas por sesión
        print(f"✓ Análisis completado: {len(value_bets)} value bets encontradas")
        return value_bets

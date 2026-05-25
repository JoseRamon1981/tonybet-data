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
        print("  Obteniendo datos reales de equipos desde ESPN…")
        sample = []
        for e in events[:20]:
            name  = e.get("name", "")
            sport = e.get("sport", "")
            ctx   = fetch_event_context(name, sport)
            entry = {
                "name": name,
                "sport": sport,
                "competition": e.get("competition"),
                "starts_at": e.get("starts_at"),
                "markets": e.get("markets", [])[:3],
            }
            if ctx:
                entry["datos_espn"] = ctx
            sample.append(entry)
        events_json = json.dumps(sample, ensure_ascii=False, indent=2)
        return (
            "Eres un analista de apuestas deportivas EXTREMADAMENTE CRITICO y conservador.\n\n"

            "FILOSOFIA: Es MEJOR NO APOSTAR que apostar con dudas. Solo recomiendas apuestas cuando tienes "
            "conviccion muy alta basada en datos reales y actuales. Si un partido es incierto, NO llamas al tool.\n\n"

            "=== COMO INTERPRETAR EL CAMPO 'datos_espn' ===\n"
            "Para cada equipo veras estas secciones. USARAS cada una de forma especifica:\n\n"

            "1. TEMPORADA (posicion, puntos, record W/D/L, GF/GC por partido):\n"
            "   - La posicion en tabla indica el nivel estructural del equipo ESTA TEMPORADA\n"
            "   - GF/pj = goles que marca por partido (crucial para Over/Under)\n"
            "   - GC/pj = goles que encaja por partido (crucial para Over/Under y BTTS)\n"
            "   - Si un equipo es top-3 vs equipo en descenso: diferencia estructural ALTA\n"
            "   - Puntos y record te dan el panorama completo de la temporada\n\n"

            "2. TEMPORADA EN CASA vs FUERA (record separado):\n"
            "   - Si el partido es EN CASA: usa el record en casa para estimar el rendimiento\n"
            "   - Si el partido es FUERA: usa el record fuera. Muchos favoritos bajan rendimiento\n"
            "   - Un equipo con 15V-0E-0P en casa tiene fortaleza local EXCEPCIONAL\n"
            "   - Un equipo con 7V-3E-9P fuera es vulnerable lejos de casa aunque sea grande\n\n"

            "3. FORMA ULT.5 (ultimos 5 partidos, cualquier competicion):\n"
            "   - Refleja el estado de forma actual (momentum)\n"
            "   - 5V-0E-0P = racha excepcional. 0V-0E-5P = crisis grave\n"
            "   - Los goles/pj en los ultimos 5 son mas representativos que la media de temporada\n\n"

            "4. ULT.5 EN CASA / FUERA (mini-record de los ultimos 5):\n"
            "   - Combina con el punto 2 para evaluar forma reciente en esa condicion\n\n"

            "5. RESULTADOS (los ultimos 5 marcadores reales):\n"
            "   - Te da contexto real: rivales, goles, si fue cerca o goleada\n"
            "   - Ayuda a detectar victorias ajustadas vs convincentes\n\n"

            "6. ULT.5 ENFRENTAMIENTOS DIRECTOS (H2H):\n"
            "   - Historico reciente entre estos dos equipos\n"
            "   - Importante para detectar patrones: quien domina, cuantos goles suele haber\n\n"

            "=== COMO USAR LOS DATOS PARA CADA MERCADO ===\n\n"

            "PARA 1X2 / DOBLE OPORTUNIDAD:\n"
            "- Necesitas diferencia CLARA de calidad: tabla + forma + local/visitante\n"
            "- Ejemplo de 80%+: equipo top-3 de local (record casa excelente) vs equipo descenso en mala forma\n"
            "- Doble oportunidad 1X: equipo de local con forma solida. Menos rentable pero mas seguro\n"
            "- NUNCA recomiendas victoria visitante a menos que la diferencia de calidad sea estructural\n\n"

            "PARA OVER/UNDER GOLES:\n"
            "- Calcula los goles esperados sumando GF/pj de ambos equipos\n"
            "- Ejemplo: equipo A marca 2.0/pj + equipo B marca 1.8/pj = ~3.8 goles esperados -> OVER 2.5 probable\n"
            "- Pero tambien considera GC/pj: si ambos encajan muchos, OVER es mas seguro\n"
            "- Si ambos equipos tienen GF+GC > 3.0 por equipo: Over 2.5 con buena probabilidad\n"
            "- Si uno de los equipos tiene GC muy bajo (< 0.8/pj): considera UNDER o BTTS No\n"
            "- Usa tambien el H2H: si los ultimos 5 directos han sido de muchos goles, refuerza Over\n\n"

            "PARA AMBOS MARCAN (BTTS):\n"
            "- Necesitas que AMBOS equipos marquen habitualmente Y encajen habitualmente\n"
            "- Si equipo A tiene GC < 0.7/pj (defensa solida): BTTS riesgo alto, descarta\n"
            "- Si ambos tienen GF > 1.5/pj Y GC > 0.8/pj: BTTS 'Si' con buena probabilidad\n\n"

            "=== UMBRAL MINIMO — OBLIGATORIO ===\n"
            "- Solo llamas al tool para selecciones con probabilidad estimada >= 80%\n"
            "- La estimacion DEBE basarse en los datos ESPN mostrados, no en suposiciones\n"
            "- Si la forma contradice lo que esperarias de la tabla: usa la FORMA (mas reciente)\n"
            "- Si no hay datos ESPN: se conservador, descarta si no hay desequilibrio EVIDENTE\n"
            "- 70-79%: descarta. <70%: descarta definitivamente\n\n"

            "=== SENALES CLARAS DE 80%+ ===\n"
            "- Top-3 de tabla (en casa, buen record local) vs bottom-3 (fuera, mal record visitante)\n"
            "- Equipo con 4-5 victorias en los ultimos 5 vs equipo con 4-5 derrotas\n"
            "- Over 2.5 cuando suma GF+GC de ambos > 4.0 goles esperados Y el H2H lo confirma\n"
            "- BTTS 'Si' cuando ambos marcan 1.5+/pj y encajan 1.0+/pj\n"
            "- Doble oportunidad 1X para favorito local con record en casa > 70% puntos posibles\n\n"

            "=== SENALES DE DESCARTE ===\n"
            "- Forma contradice la tabla (favorito en crisis: 3+ derrotas recientes)\n"
            "- Partido equilibrado en tabla Y en forma\n"
            "- Partido con implicaciones tacticas (ya campeones, ya descendidos, ya sin nada)\n"
            "- No hay datos ESPN Y las cuotas no muestran desequilibrio claro (< 60% implicita)\n"
            "- H2H muestra que el supuesto favorito pierde historicamente contra este rival\n\n"

            "=== CRITERIOS FINALES ===\n"
            "- EV minimo: +4% sobre el valor justo\n"
            "- Cuotas objetivo: 1.20-1.70 (alta probabilidad = cuota baja, es normal)\n"
            "- Maximo 5 apuestas por sesion. 0 si nada cumple el 80%\n"
            "- Mercados: 1X2, Doble oportunidad, Over/Under, Ambos marcan, Handicap claro\n\n"

            f"Bankroll: {self.bankroll}€\n\n"

            "IMPORTANTE: Se honesto y riguroso. Si revisas todos los partidos y ninguno cumple el 80% "
            "con los datos disponibles, no llames al tool y explica brevemente por que no hay oportunidades.\n\n"

            "EVENTOS (con datos reales ESPN donde disponibles):\n"
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
        print(f"✓ Análisis completado: {len(value_bets)} value bets encontradas")
        return value_bets

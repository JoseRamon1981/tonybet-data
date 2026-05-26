"""
Tonybet Betting Advisor — Dashboard Web (Streamlit)
Lee los datos publicados en GitHub por el agente local.
"""
import json
from datetime import date, datetime, timedelta

import requests
import streamlit as st

GITHUB_RAW  = "https://raw.githubusercontent.com/JoseRamon1981/tonybet-data/main"
RECS_URL    = f"{GITHUB_RAW}/recommendations_latest.json"
LOG_URL     = f"{GITHUB_RAW}/bets_log.json"
PREVIEW_URL = f"{GITHUB_RAW}/preview_latest.json"
EVENTS_URL  = f"{GITHUB_RAW}/events_latest.json"
ACTIONS_URL = "https://github.com/JoseRamon1981/tonybet-data/actions/workflows/advisor.yml"

# Icono por deporte
SPORT_ICONS: dict[str, str] = {
    "Fútbol":              "⚽",
    "Tenis":               "🎾",
    "Baloncesto":          "🏀",
    "Hockey hielo":        "🏒",
    "Béisbol":             "⚾",
    "Fútbol americano":    "🏈",
    "MMA":                 "🥊",
    "Boxeo":               "🥊",
    "Rugby Union":         "🏉",
    "Rugby League":        "🏉",
    "Cricket":             "🏏",
    "Golf":                "⛳",
    "Dardos":              "🎯",
    "Voleibol":            "🏐",
    "Balonmano":           "🤾",
}

# Color de borde por deporte
SPORT_COLORS: dict[str, str] = {
    "Fútbol":              "#16a34a",
    "Tenis":               "#ca8a04",
    "Baloncesto":          "#ea580c",
    "Hockey hielo":        "#0284c7",
    "Béisbol":             "#dc2626",
    "Fútbol americano":    "#7c3aed",
    "MMA":                 "#be123c",
    "Boxeo":               "#be123c",
    "Rugby Union":         "#065f46",
    "Rugby League":        "#065f46",
    "Cricket":             "#92400e",
    "Golf":                "#166534",
    "Dardos":              "#581c87",
    "Voleibol":            "#0e7490",
    "Balonmano":           "#7e22ce",
}


def _sport_icon(sport: str) -> str:
    return SPORT_ICONS.get(sport, "🏅")


def _sport_color(sport: str) -> str:
    return SPORT_COLORS.get(sport, "#6b7280")


def fetch_json(url: str):
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def ev_color(ev: float) -> str:
    if ev >= 0.08:
        return "#16a34a"
    if ev >= 0.04:
        return "#ca8a04"
    return "#dc2626"


def _prob_bar(prob: float) -> str:
    filled = round(prob * 20)
    empty  = 20 - filled
    return "█" * filled + "░" * empty


def _market_nav(market: str, selection: str) -> str:
    m = market.lower()
    if any(k in m for k in ("total", "over", "under", "goles", "puntos", "runs")):
        line = selection.replace("Over ", "Más de ").replace("Under ", "Menos de ")
        return f"Partido → pestaña **Totales/Goles** → selecciona **{line}**"
    if any(k in m for k in ("ambos", "btts")):
        return f"Partido → **Ambos equipos marcan** → **{selection}**"
    if any(k in m for k in ("doble", "double")):
        return f"Partido → **Doble oportunidad** → **{selection}**"
    if any(k in m for k in ("handicap", "hándicap", "spread")):
        return f"Partido → pestaña **Hándicap** → **{selection}**"
    return f"Busca el partido → mercado **{market}** → **{selection}**"


# ── page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Tonybet Advisor",
    page_icon="🎯",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  html, body, [class*="css"] { font-size: 16px !important; }

  .bet-card {
    background: #f9fafb;
    border-radius: 12px;
    padding: 16px 14px;
    margin-bottom: 12px;
    border-left: 5px solid #6b7280;
    box-shadow: 0 1px 6px rgba(0,0,0,0.08);
    color: #111 !important;
  }
  .bet-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 6px;
  }
  .bet-title {
    font-size: 1.05em;
    font-weight: 700;
    color: #111;
    flex: 1;
  }
  .ev-pill {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 20px;
    font-weight: 800;
    font-size: 0.9em;
    white-space: nowrap;
    margin-left: 8px;
  }
  .bet-meta {
    font-size: 0.82em;
    color: #6b7280;
    margin-bottom: 8px;
  }
  .bet-row {
    font-size: 0.95em;
    color: #222;
    margin: 4px 0;
  }
  .prob-bar {
    font-family: monospace;
    font-size: 0.85em;
    color: #374151;
  }
  .stake-line {
    margin-top: 10px;
    font-size: 1em;
    font-weight: 700;
    color: #1d4ed8;
  }
  .nav-hint {
    margin-top: 8px;
    font-size: 0.82em;
    color: #6b7280;
    background: #f3f4f6;
    border-radius: 6px;
    padding: 6px 10px;
  }
</style>
""", unsafe_allow_html=True)

st.title("🎯 Tonybet Advisor")
st.caption("Recomendaciones de apuestas con valor esperado positivo — todos los deportes")

tab1, tab2, tab3, tab4 = st.tabs(["📋 Hoy", "🔭 Mañana", "💬 Consultar", "📊 Estadísticas"])


# ── TAB 1: Recomendaciones de hoy ────────────────────────────────────────────

with tab1:
    data = fetch_json(RECS_URL)

    if not data:
        st.info("No hay recomendaciones publicadas todavía.")
        st.link_button("🚀 Ejecutar advisor ahora", ACTIONS_URL, use_container_width=True)
        st.stop()

    updated     = data.get("updated_at", "—")
    bets        = data.get("bets", [])
    today_str   = datetime.now().strftime("%Y-%m-%d")
    updated_date = updated[:10] if updated else ""

    if updated_date == today_str:
        st.success(f"✅ Análisis de hoy — actualizado a las {updated[11:]}")
    else:
        st.warning(f"⚠️ Última actualización: {updated}  ·  Datos desactualizados")
        st.link_button("🚀 Actualizar ahora (GitHub Actions)", ACTIONS_URL, use_container_width=True)

    if not bets:
        st.info(
            "🔍 El agente analizó el mercado en todos los deportes y no encontró apuestas "
            "con valor esperado positivo suficiente hoy. Vuelve en la próxima actualización."
        )
    else:
        # Filtro por deporte
        sports_in_bets = sorted({b.get("sport", "—") for b in bets})
        if len(sports_in_bets) > 1:
            sports_in_bets = ["Todos"] + sports_in_bets
            sport_filter = st.selectbox("Filtrar por deporte", sports_in_bets, index=0)
            filtered_bets = bets if sport_filter == "Todos" else [b for b in bets if b.get("sport") == sport_filter]
        else:
            filtered_bets = bets

        n = len(filtered_bets)
        total_stake = sum(b.get("recommended_stake", 0) for b in filtered_bets)
        st.success(f"**{n} value bet{'s' if n != 1 else ''} encontrada{'s' if n != 1 else ''}**  ·  Stake total: **{total_stake:.2f}€**")

        for b in filtered_bets:
            ev    = b.get("expected_value", 0)
            prob  = b.get("estimated_probability", 0)
            sport = b.get("sport", "")
            color = _sport_color(sport)
            ev_c  = ev_color(ev)
            icon  = _sport_icon(sport)

            nav = _market_nav(b.get("market", ""), b.get("selection", ""))
            bar = _prob_bar(prob)

            st.markdown(f"""
            <div class="bet-card" style="border-left-color:{color}">
              <div class="bet-header">
                <div class="bet-title">{icon} {b.get('event','')}</div>
                <span class="ev-pill" style="background:{ev_c}22;color:{ev_c};border:1px solid {ev_c}">
                  EV {ev*100:+.1f}%
                </span>
              </div>
              <div class="bet-meta">
                {sport} &nbsp;·&nbsp; {b.get('market','')} &nbsp;·&nbsp; {updated}
              </div>
              <div class="bet-row">✅ <b>Apuesta:</b> {b.get('selection','')} &nbsp;@&nbsp; <b>{b.get('odds',0):.2f}</b></div>
              <div class="bet-row prob-bar">📊 Probabilidad real: {prob*100:.0f}%  {bar}</div>
              <div class="stake-line">💶 Stake recomendado: {b.get('recommended_stake',0):.2f}€</div>
              <div class="nav-hint">📍 Cómo apostar en Tonybet: {nav}</div>
            </div>
            """, unsafe_allow_html=True)


# ── TAB 2: Mañana (preview) ───────────────────────────────────────────────────

with tab2:
    prev = fetch_json(PREVIEW_URL)

    if not prev:
        st.warning("⏳ Sin datos de mañana todavía.")
        st.link_button("🚀 Generar preview ahora", ACTIONS_URL, use_container_width=True)
    else:
        for_date  = prev.get("for_date", "")
        updated   = prev.get("updated_at", "—")
        total_ev  = prev.get("total_events", 0)
        analyzed  = prev.get("analyzed_count", 0)
        analysis  = prev.get("analysis", "")

        tomorrow_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        today_str    = datetime.now().strftime("%Y-%m-%d")

        try:
            display_date = datetime.strptime(for_date, "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            display_date = for_date

        if for_date == tomorrow_str:
            st.success(f"✅ Vista previa actualizada para mañana **{display_date}**")
        elif for_date == today_str:
            st.warning(f"⚠️ Este preview es de hoy ({display_date}) — se actualizará esta tarde/noche.")
        else:
            st.error(f"🔴 Datos desactualizados ({display_date})")
            st.link_button("🚀 Actualizar (GitHub Actions)", ACTIONS_URL, use_container_width=True)

        st.caption(f"Generado: {updated}  ·  {analyzed} de {total_ev} eventos analizados")
        st.markdown("---")
        st.markdown(analysis)


# ── TAB 3: Consultar ─────────────────────────────────────────────────────────

with tab3:
    st.markdown("### 💬 Pregunta sobre los eventos disponibles")
    st.caption("Los datos incluyen todos los deportes obtenidos en la última ejecución del advisor.")

    ev_snap = fetch_json(EVENTS_URL)

    if not ev_snap or ev_snap.get("total", 0) == 0:
        st.warning("Sin datos de eventos disponibles todavía.")
        st.link_button("🚀 Ejecutar advisor ahora", ACTIONS_URL, use_container_width=True)
    else:
        updated_ev = ev_snap.get("updated_at", "—")
        total_ev   = ev_snap.get("total", 0)
        events_raw = ev_snap.get("events", [])

        # Mostrar resumen de deportes disponibles
        by_sport: dict[str, int] = {}
        for e in events_raw:
            sp = e.get("deporte") or e.get("sport") or "—"
            by_sport[sp] = by_sport.get(sp, 0) + 1

        st.caption(f"Datos del {updated_ev}  ·  {total_ev} eventos")
        sport_summary = "  ".join(f"{_sport_icon(sp)} {sp} ({n})" for sp, n in sorted(by_sport.items()))
        st.caption(sport_summary)

        # API key management
        @st.cache_resource
        def _key_store():
            return {"key": ""}

        key_store = _key_store()
        if key_store["key"] and not st.session_state.get("api_key"):
            st.session_state["api_key"] = key_store["key"]

        if not st.session_state.get("api_key"):
            with st.expander("🔑 Introduce tu clave Anthropic API (solo una vez)", expanded=True):
                st.caption("Se guarda en el servidor mientras la app esté activa.")
                key_input = st.text_input("Clave Anthropic API", type="password", placeholder="sk-ant-api03-...")
                if st.button("Guardar clave"):
                    if key_input.startswith("sk-ant"):
                        key_store["key"] = key_input
                        st.session_state["api_key"] = key_input
                        st.success("¡Clave guardada!")
                        st.rerun()
                    else:
                        st.error("La clave debe empezar por sk-ant...")
        else:
            col_k1, col_k2 = st.columns([3, 1])
            col_k1.success("🔑 Clave API activa — ya puedes preguntar")
            if col_k2.button("Borrar"):
                key_store["key"] = ""
                st.session_state["api_key"] = ""
                st.rerun()

        # Ejemplos de preguntas
        with st.expander("💡 Ejemplos de preguntas"):
            st.markdown(
                "- ¿Qué partidos hay de La Liga hoy?\n"
                "- ¿Cuáles son las cuotas del partido de tenis más interesante?\n"
                "- ¿Hay partidos de la NBA esta noche?\n"
                "- Dame los 3 partidos de fútbol con mayor desequilibrio en cuotas\n"
                "- ¿Qué hay en la NHL hoy y quiénes son los favoritos?\n"
                "- ¿Hay algún partido de MMA o boxeo este fin de semana?"
            )

        # Chat
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []

        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        question = st.chat_input("¿Qué quieres saber sobre los eventos de hoy?")

        if question:
            st.session_state.chat_history.append({"role": "user", "content": question})
            with st.chat_message("user"):
                st.markdown(question)

            api_key = ""
            try:
                api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
            except Exception:
                pass
            if not api_key:
                api_key = st.session_state.get("api_key", "")

            if not api_key:
                st.error("Introduce tu clave de Anthropic arriba para usar el chat.")
            else:
                try:
                    import anthropic
                    client = anthropic.Anthropic(api_key=api_key)
                    events_json = json.dumps(events_raw, ensure_ascii=False)

                    prompt = (
                        f"Eres un asistente experto en apuestas deportivas multideporte. "
                        f"El usuario pregunta: \"{question}\"\n\n"
                        f"Responde usando únicamente los datos de los eventos disponibles a continuación. "
                        f"Sé concreto, claro y organizado. Incluye cuotas cuando las haya. "
                        f"Si no hay eventos que coincidan, dilo claramente.\n\n"
                        f"DATOS ({total_ev} eventos de todos los deportes):\n{events_json}"
                    )

                    with st.chat_message("assistant"):
                        with st.spinner("Consultando…"):
                            response = client.messages.create(
                                model="claude-sonnet-4-6",
                                max_tokens=2000,
                                messages=[{"role": "user", "content": prompt}],
                            )
                            answer = response.content[0].text
                            st.markdown(answer)

                    st.session_state.chat_history.append({"role": "assistant", "content": answer})

                except Exception as e:
                    st.error(f"Error al consultar Claude: {e}")

        if st.session_state.chat_history:
            if st.button("🗑️ Limpiar conversación"):
                st.session_state.chat_history = []
                st.rerun()


# ── TAB 4: Estadísticas ───────────────────────────────────────────────────────

with tab4:
    log = fetch_json(LOG_URL)

    if not log:
        st.info("Sin historial todavía. Las apuestas registradas aparecerán aquí.")
    else:
        cutoff  = (date.today() - timedelta(days=30)).isoformat()
        recent  = [r for r in log if r.get("date", "") >= cutoff]
        settled = [r for r in recent if r.get("result") in ("won", "lost")]
        pending = [r for r in recent if r.get("result") == "pending"]

        if not settled:
            st.warning("Sin apuestas liquidadas en los últimos 30 días.")
            if pending:
                st.info(f"{len(pending)} apuesta(s) pendientes de resultado.")
        else:
            total_stake  = sum(r["stake"] for r in settled)
            total_profit = sum(r["profit"] for r in settled)
            won_count    = sum(1 for r in settled if r["result"] == "won")
            roi          = total_profit / total_stake * 100 if total_stake else 0
            winrate      = won_count / len(settled) * 100
            avg_odds     = sum(r["odds"] for r in settled) / len(settled)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Beneficio",   f"{total_profit:+.2f}€")
            c2.metric("ROI",         f"{roi:+.1f}%")
            c3.metric("Acierto",     f"{winrate:.0f}%")
            c4.metric("Cuota media", f"{avg_odds:.2f}")

            st.markdown("---")

            # P&L por deporte
            by_sport_profit: dict[str, float] = {}
            for r in settled:
                sp = r.get("sport", "Otro")
                by_sport_profit[sp] = by_sport_profit.get(sp, 0) + r["profit"]

            if len(by_sport_profit) > 1:
                st.markdown("**P&L por deporte (últimos 30 días)**")
                import pandas as pd
                df_sport = pd.DataFrame(
                    {"Deporte": list(by_sport_profit.keys()), "P&L (€)": list(by_sport_profit.values())}
                ).sort_values("P&L (€)", ascending=False)
                st.bar_chart(df_sport.set_index("Deporte"))

            # P&L diario
            by_day: dict[str, float] = {}
            for r in settled:
                d = r["date"]
                by_day[d] = by_day.get(d, 0) + r["profit"]

            if by_day:
                import pandas as pd
                st.markdown("**P&L diario**")
                df = pd.DataFrame(
                    {"Fecha": list(by_day.keys()), "P&L (€)": list(by_day.values())}
                ).sort_values("Fecha")
                st.bar_chart(df.set_index("Fecha"))

            # Historial reciente
            st.markdown("**Historial reciente**")
            for r in sorted(recent, key=lambda x: x["date"], reverse=True)[:25]:
                icon       = "✅" if r["result"] == "won" else "❌" if r["result"] == "lost" else "⏳"
                sport_icon = _sport_icon(r.get("sport", ""))
                profit_str = f"{r['profit']:+.2f}€" if r["result"] in ("won", "lost") else "—"
                st.markdown(
                    f"{icon} {sport_icon} `{r['date']}` **{r['event']}** — "
                    f"{r['selection']} @ {r['odds']:.2f} "
                    f"(stake {r['stake']:.2f}€) **{profit_str}**"
                )

        if pending:
            st.markdown(f"---\n**Pendientes de resultado:** {len(pending)}")
            for r in pending:
                sp_icon = _sport_icon(r.get("sport", ""))
                st.markdown(
                    f"⏳ {sp_icon} `{r['date']}` {r['event']} — {r['selection']} @ {r['odds']:.2f}"
                )

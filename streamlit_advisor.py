"""
Tonybet Betting Advisor — Web Dashboard (Streamlit)
Reads data published to GitHub by the local agent.
"""
import json
from datetime import date, timedelta

import requests
import streamlit as st

GITHUB_RAW    = "https://raw.githubusercontent.com/JoseRamon1981/tonybet-data/main"
RECS_URL      = f"{GITHUB_RAW}/recommendations_latest.json"
LOG_URL       = f"{GITHUB_RAW}/bets_log.json"
PREVIEW_URL   = f"{GITHUB_RAW}/preview_latest.json"
EVENTS_URL    = f"{GITHUB_RAW}/events_latest.json"


# ── helpers ───────────────────────────────────────────────────────────────────

def fetch_json(url: str) -> dict | list | None:
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def ev_color(ev: float) -> str:
    if ev >= 0.08:
        return "#00c851"
    if ev >= 0.04:
        return "#ffbb33"
    return "#ff4444"


# ── page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Tonybet Advisor",
    page_icon="🎯",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  /* Mobile-first typography */
  html, body, [class*="css"] { font-size: 17px !important; }

  .bet-card {
    background: #ffffff;
    border-radius: 14px;
    padding: 18px 16px;
    margin-bottom: 14px;
    border-left: 5px solid #7c3aed;
    box-shadow: 0 2px 8px rgba(0,0,0,0.10);
    color: #111111 !important;
  }
  .bet-title {
    font-size: 1.1em;
    font-weight: 700;
    color: #111111;
    margin-bottom: 4px;
  }
  .bet-sub {
    font-size: 0.9em;
    color: #555555;
    margin-bottom: 10px;
  }
  .bet-row {
    font-size: 1em;
    color: #222222;
    margin: 3px 0;
  }
  .ev-badge {
    display: inline-block;
    padding: 3px 12px;
    border-radius: 20px;
    font-weight: 800;
    font-size: 1em;
    margin-left: 6px;
  }
  .stake-line {
    margin-top: 10px;
    font-size: 1.05em;
    font-weight: 600;
    color: #7c3aed;
  }
</style>
""", unsafe_allow_html=True)


# ── main ─────────────────────────────────────────────────────────────────────

st.title("🎯 Tonybet Advisor")
st.caption("Recomendaciones de apuestas con valor esperado positivo")

tab1, tab2, tab3, tab4 = st.tabs(["📋 Hoy", "🔭 Mañana", "💬 Consultar", "📊 Estadísticas"])


# ── TAB 1: Recomendaciones ────────────────────────────────────────────────────

with tab1:
    data = fetch_json(RECS_URL)

    ACTIONS_URL = "https://github.com/JoseRamon1981/tonybet-data/actions/workflows/advisor.yml"

    if not data:
        st.info("No hay recomendaciones publicadas todavía.")
        st.link_button("🚀 Ejecutar advisor ahora", ACTIONS_URL, use_container_width=True)
    else:
        updated = data.get("updated_at", "—")
        bets    = data.get("bets", [])

        from datetime import datetime as _dt
        today_str = _dt.now().strftime("%Y-%m-%d")
        updated_date = updated[:10] if updated else ""
        if updated_date == today_str:
            st.success(f"✅ Análisis de hoy — {updated}")
        else:
            st.warning(f"⚠️ Última actualización: {updated}  ·  Datos desactualizados")
            st.link_button("🚀 Actualizar ahora (GitHub Actions)", ACTIONS_URL, use_container_width=True)

        if not bets:
            st.info("🔍 El agente analizó el mercado y no encontró apuestas con 80%+ de confianza hoy. Vuelve mañana.")
        else:
            st.success(f"**{len(bets)} value bet(s) encontradas**")

            for b in bets:
                ev  = b.get("expected_value", 0)
                col = ev_color(ev)
                st.markdown(f"""
                <div class="bet-card">
                  <div class="bet-title">{b.get('event','')}</div>
                  <div class="bet-sub">{b.get('sport','')} &nbsp;·&nbsp; {b.get('market','')}</div>
                  <div class="bet-row">✅ <b>Selección:</b> {b.get('selection','')}</div>
                  <div class="bet-row">📊 <b>Cuota:</b> {b.get('odds', 0):.2f}
                    <span class="ev-badge" style="background:{col}22; color:{col}; border:1px solid {col}">
                      EV {ev*100:+.1f}%
                    </span>
                  </div>
                  <div class="stake-line">💶 Stake: {b.get('recommended_stake', 0):.2f}€</div>
                </div>
                """, unsafe_allow_html=True)

            total = sum(b.get("recommended_stake", 0) for b in bets)
            st.markdown(f"**Stake total:** {total:.2f}€")


# ── TAB 2: Mañana (preview) ───────────────────────────────────────────────────

with tab2:
    prev = fetch_json(PREVIEW_URL)

    ACTIONS_URL = "https://github.com/JoseRamon1981/tonybet-data/actions/workflows/advisor.yml"

    if not prev:
        st.warning("⏳ Sin datos de mañana todavía.")
        st.link_button("🚀 Ejecutar advisor ahora", ACTIONS_URL, use_container_width=True)
    else:
        from datetime import datetime, timedelta
        for_date  = prev.get("for_date", "")          # "2026-05-24"
        updated   = prev.get("updated_at", "—")        # "23/05/2026 20:15"
        total_ev  = prev.get("total_events", 0)
        analyzed  = prev.get("analyzed_count", 0)
        analysis  = prev.get("analysis", "")

        # Work out if the preview is for tomorrow or stale
        tomorrow_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        today_str    = datetime.now().strftime("%Y-%m-%d")
        is_fresh     = for_date == tomorrow_str
        is_today     = for_date == today_str   # preview generated for today (outdated)

        # Human-readable date
        try:
            display_date = datetime.strptime(for_date, "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            display_date = for_date

        if is_fresh:
            st.success(f"✅ Vista previa actualizada para **mañana {display_date}**")
        elif is_today:
            st.warning(f"⚠️ Esta vista previa es de **hoy {display_date}** — se actualizará esta tarde/noche.")
        else:
            st.error(f"🔴 Datos desactualizados ({display_date}).")
            st.link_button("🚀 Actualizar ahora (GitHub Actions)", ACTIONS_URL, use_container_width=True)

        st.caption(f"Generado el {updated} · {analyzed} de {total_ev} eventos analizados")
        st.markdown("---")
        st.markdown(analysis)


# ── TAB 3: Consultar ─────────────────────────────────────────────────────────

with tab3:
    st.markdown("### 💬 Pregunta sobre los partidos de hoy")
    st.caption("Los datos se actualizan cada vez que se ejecuta el advisor (automático cada día a las 10h).")

    ev_snap = fetch_json(EVENTS_URL)

    if not ev_snap:
        st.warning("Datos de eventos no disponibles todavía.")
        st.link_button("🚀 Ejecutar advisor ahora", "https://github.com/JoseRamon1981/tonybet-data/actions/workflows/advisor.yml", use_container_width=True)
    else:
        updated_ev = ev_snap.get("updated_at", "—")
        total_ev   = ev_snap.get("total", 0)
        st.caption(f"Datos del {updated_ev} · {total_ev} eventos cargados")

        # Persistent API key cache (survives tab changes and refreshes)
        @st.cache_resource
        def _key_store():
            return {"key": ""}

        key_store = _key_store()

        # Sync cache → session state
        if key_store["key"] and not st.session_state.get("api_key"):
            st.session_state["api_key"] = key_store["key"]

        if not st.session_state.get("api_key"):
            with st.expander("🔑 Introduce tu clave Anthropic (solo la primera vez)", expanded=True):
                st.caption("Se guarda en el servidor mientras la app esté activa. No se comparte con nadie.")
                key_input = st.text_input("Clave Anthropic API", type="password", placeholder="sk-ant-api03-...")
                if st.button("Guardar clave"):
                    if key_input.startswith("sk-ant"):
                        key_store["key"] = key_input
                        st.session_state["api_key"] = key_input
                        st.success("¡Clave guardada! No tendrás que introducirla de nuevo.")
                        st.rerun()
                    else:
                        st.error("La clave debe empezar por sk-ant...")
        else:
            col_k1, col_k2 = st.columns([3, 1])
            col_k1.success("🔑 Clave API configurada — ya puedes preguntar")
            if col_k2.button("Borrar"):
                key_store["key"] = ""
                st.session_state["api_key"] = ""
                st.rerun()

        # Chat history stored in session state
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []

        # Show previous messages
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # Input
        question = st.chat_input("¿Qué quieres saber? Ej: qué hay en La Liga hoy, cuotas del Real Madrid...")

        if question:
            # Show user message
            st.session_state.chat_history.append({"role": "user", "content": question})
            with st.chat_message("user"):
                st.markdown(question)

            # Get API key: secrets → session state → error
            import json as _json
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
                    events_json = _json.dumps(ev_snap.get("events", []), ensure_ascii=False)

                    prompt = (
                        f"Eres un asistente experto en apuestas deportivas. "
                        f"El usuario pregunta: \"{question}\"\n\n"
                        f"Responde usando únicamente los datos de Tonybet que tienes a continuación. "
                        f"Sé concreto, claro y organizado. Incluye cuotas cuando las haya. "
                        f"Si no hay eventos que coincidan, dilo.\n\n"
                        f"DATOS TONYBET ({total_ev} eventos):\n{events_json}"
                    )

                    with st.chat_message("assistant"):
                        with st.spinner("Consultando..."):
                            response = client.messages.create(
                                model="claude-sonnet-4-6",
                                max_tokens=1500,
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
                st.info(f"{len(pending)} apuesta(s) pendiente(s) de resultado.")
        else:
            total_stake  = sum(r["stake"] for r in settled)
            total_profit = sum(r["profit"] for r in settled)
            won_count    = sum(1 for r in settled if r["result"] == "won")
            roi          = total_profit / total_stake * 100 if total_stake else 0
            winrate      = won_count / len(settled) * 100

            c1, c2, c3 = st.columns(3)
            c1.metric("Beneficio", f"{total_profit:+.2f}€")
            c2.metric("ROI", f"{roi:+.1f}%")
            c3.metric("Acierto", f"{winrate:.0f}%")

            st.markdown("---")

            # Daily P&L chart
            by_day: dict[str, float] = {}
            for r in settled:
                d = r["date"]
                by_day[d] = by_day.get(d, 0) + r["profit"]

            if by_day:
                import pandas as pd
                df = pd.DataFrame(
                    {"Fecha": list(by_day.keys()), "P&L (€)": list(by_day.values())}
                ).sort_values("Fecha")
                st.bar_chart(df.set_index("Fecha"))

            st.markdown("**Historial reciente**")
            for r in sorted(recent, key=lambda x: x["date"], reverse=True)[:20]:
                icon  = "✅" if r["result"] == "won" else "❌" if r["result"] == "lost" else "⏳"
                profit_str = f"{r['profit']:+.2f}€" if r["result"] in ("won","lost") else ""
                st.markdown(
                    f"{icon} `{r['date']}` **{r['event']}** — {r['selection']} @ {r['odds']:.2f} "
                    f"(stake {r['stake']:.2f}€) {profit_str}"
                )

        if pending:
            st.markdown(f"---\n**Pendientes:** {len(pending)}")
            for r in pending:
                st.markdown(f"⏳ `{r['date']}` {r['event']} — {r['selection']} @ {r['odds']:.2f}")

"""
Tonybet Betting Advisor — Dashboard Web (Streamlit)
Multi-tenant SaaS: Supabase Auth + Stripe Billing.
"""
import json
import os
from datetime import date, datetime, timedelta

import requests
import streamlit as st

GITHUB_RAW  = "https://raw.githubusercontent.com/JoseRamon1981/tonybet-data/main"
RECS_URL    = f"{GITHUB_RAW}/recommendations_latest.json"
PREVIEW_URL = f"{GITHUB_RAW}/preview_latest.json"
EVENTS_URL  = f"{GITHUB_RAW}/events_latest.json"
ACTIONS_URL = "https://github.com/JoseRamon1981/tonybet-data/actions/workflows/advisor.yml"

SPORT_ICONS: dict[str, str] = {
    "Fútbol":           "⚽", "Tenis":          "🎾", "Baloncesto":       "🏀",
    "Hockey hielo":     "🏒", "Béisbol":        "⚾", "Fútbol americano": "🏈",
    "MMA":              "🥊", "Boxeo":          "🥊", "Rugby Union":      "🏉",
    "Rugby League":     "🏉", "Cricket":        "🏏", "Golf":            "⛳",
    "Dardos":           "🎯", "Voleibol":       "🏐", "Balonmano":       "🤾",
}

SPORT_COLORS: dict[str, str] = {
    "Fútbol":           "#16a34a", "Tenis":          "#ca8a04", "Baloncesto":       "#ea580c",
    "Hockey hielo":     "#0284c7", "Béisbol":        "#dc2626", "Fútbol americano": "#7c3aed",
    "MMA":              "#be123c", "Boxeo":          "#be123c", "Rugby Union":      "#065f46",
    "Rugby League":     "#065f46", "Cricket":        "#92400e", "Golf":            "#166534",
    "Dardos":           "#581c87", "Voleibol":       "#0e7490", "Balonmano":       "#7e22ce",
}

# What each tier unlocks
TIER_LIMITS: dict[str, dict] = {
    "free":    {"max_bets": 2,    "chat": False, "preview": False},
    "pro":     {"max_bets": None, "chat": True,  "preview": True},
    "premium": {"max_bets": None, "chat": True,  "preview": True},
}


def _sport_icon(sport: str) -> str:  return SPORT_ICONS.get(sport, "🏅")
def _sport_color(sport: str) -> str: return SPORT_COLORS.get(sport, "#6b7280")


def fetch_json(url: str):
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def ev_color(ev: float) -> str:
    if ev >= 0.08: return "#16a34a"
    if ev >= 0.04: return "#ca8a04"
    return "#dc2626"


def prob_color(prob: float) -> str:
    if prob >= 0.80: return "#16a34a"
    if prob >= 0.70: return "#ca8a04"
    return "#2563eb"


def _prob_bar(prob: float) -> str:
    filled = round(prob * 20)
    return "█" * filled + "░" * (20 - filled)


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


def _upgrade_button(user: dict, target_tier: str, label: str):
    try:
        from saas.billing import create_checkout_url
        url = create_checkout_url(user["id"], user["email"], target_tier)
        if url:
            st.link_button(label, url, use_container_width=True, type="primary")
    except Exception:
        pass


# ── Page config (must be first Streamlit call) ────────────────────────────────

st.set_page_config(
    page_title="Tonybet Advisor",
    page_icon="🎯",
    layout="centered",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  html, body, [class*="css"] { font-size: 16px !important; }
  .bet-card {
    background: #f9fafb; border-radius: 12px; padding: 16px 14px;
    margin-bottom: 12px; border-left: 5px solid #6b7280;
    box-shadow: 0 1px 6px rgba(0,0,0,0.08); color: #111 !important;
  }
  .bet-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px; }
  .bet-title  { font-size: 1.05em; font-weight: 700; color: #111; flex: 1; }
  .ev-pill    { display: inline-block; padding: 2px 10px; border-radius: 20px; font-weight: 800;
                font-size: 0.9em; white-space: nowrap; margin-left: 8px; }
  .bet-meta   { font-size: 0.82em; color: #6b7280; margin-bottom: 8px; }
  .bet-row    { font-size: 0.95em; color: #222; margin: 4px 0; }
  .prob-bar   { font-family: monospace; font-size: 0.85em; color: #374151; }
  .stake-line { margin-top: 10px; font-size: 1em; font-weight: 700; color: #1d4ed8; }
  .prob-badge { display: inline-block; padding: 4px 14px; border-radius: 20px; font-weight: 800;
                font-size: 1.1em; margin-left: 6px; }
  .nav-hint   { margin-top: 8px; font-size: 0.82em; color: #6b7280; background: #f3f4f6;
                border-radius: 6px; padding: 6px 10px; }
  .locked-card { background: #f3f4f6; border-radius: 12px; padding: 24px; text-align: center;
                 border: 2px dashed #d1d5db; margin-bottom: 12px; }
</style>
""", unsafe_allow_html=True)


# ── Auth gate ─────────────────────────────────────────────────────────────────

# Handle Stripe payment return (session_id in URL)
raw_session_id = st.query_params.get("session_id", "")
if raw_session_id and st.session_state.get("supabase_user"):
    try:
        from saas.billing import verify_and_activate
        activated = verify_and_activate(raw_session_id, st.session_state["supabase_user"]["id"])
        if activated:
            st.session_state["subscription_tier"] = activated
            st.query_params.clear()
    except Exception:
        pass

if os.environ.get("SUPABASE_URL"):
    from saas.auth import require_auth, render_sidebar
    user, tier = require_auth()
    if user is None:
        st.stop()
    render_sidebar(user, tier)
else:
    # Local / demo mode: no auth required, full access
    user = {"id": "local", "email": "demo@local.dev"}
    tier = "premium"

limits      = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
has_supabase = bool(os.environ.get("SUPABASE_URL")) and user["id"] != "local"


# ── Main app ──────────────────────────────────────────────────────────────────

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

    updated      = data.get("updated_at", "—")
    bets         = data.get("bets", [])
    today_str    = datetime.now().strftime("%Y-%m-%d")
    updated_date = updated[:10] if updated else ""

    if updated_date == today_str:
        st.success(f"✅ Análisis de hoy — actualizado a las {updated[11:]}")
    else:
        st.warning(f"⚠️ Última actualización: {updated}  ·  Datos desactualizados")
        st.link_button("🚀 Actualizar ahora (GitHub Actions)", ACTIONS_URL, use_container_width=True)

    if not bets:
        st.info("🔍 No se encontraron value bets con EV positivo hoy. Vuelve en la próxima actualización.")
    else:
        sports_in_bets = sorted({b.get("sport", "—") for b in bets})
        if len(sports_in_bets) > 1:
            sport_filter  = st.selectbox("Filtrar por deporte", ["Todos"] + sports_in_bets, index=0)
            filtered_bets = bets if sport_filter == "Todos" else [b for b in bets if b.get("sport") == sport_filter]
        else:
            filtered_bets = bets

        max_bets     = limits["max_bets"]
        visible_bets = filtered_bets if max_bets is None else filtered_bets[:max_bets]
        locked_count = 0 if max_bets is None else max(0, len(filtered_bets) - max_bets)

        n           = len(filtered_bets)
        total_stake = sum(b.get("recommended_stake", 0) for b in visible_bets)
        st.success(
            f"**{n} value bet{'s' if n != 1 else ''} encontrada{'s' if n != 1 else ''}**"
            f"  ·  Stake visible: **{total_stake:.2f}€**"
        )

        if tier in ("pro", "premium") and has_supabase:
            if st.button("📥 Guardar apuestas de hoy en mi historial", key="save_bets"):
                try:
                    from saas.db import save_user_bets
                    n_saved = save_user_bets(user["id"], bets)
                    st.success(f"{n_saved} apuesta(s) guardadas en tu historial personal.")
                except Exception as e:
                    st.error(f"Error guardando: {e}")

        for b in visible_bets:
            ev     = b.get("expected_value", 0)
            prob   = b.get("estimated_probability", 0)
            sport  = b.get("sport", "")
            color  = _sport_color(sport)
            prob_c = prob_color(prob)
            nav    = _market_nav(b.get("market", ""), b.get("selection", ""))
            bar    = _prob_bar(prob)

            st.markdown(f"""
            <div class="bet-card" style="border-left-color:{color}">
              <div class="bet-header">
                <div class="bet-title">{_sport_icon(sport)} {b.get('event','')}</div>
                <span class="ev-pill" style="background:{ev_color(ev)}22;color:{ev_color(ev)};border:1px solid {ev_color(ev)}">
                  EV {ev*100:+.1f}%
                </span>
              </div>
              <div class="bet-meta">{sport} &nbsp;·&nbsp; {b.get('market','')} &nbsp;·&nbsp; {updated}</div>
              <div class="bet-row">✅ <b>Apuesta:</b> {b.get('selection','')} &nbsp;@&nbsp; <b>{b.get('odds',0):.2f}</b></div>
              <div class="bet-row" style="margin-top:8px;">
                🎯 <b>Probabilidad de éxito:</b>
                <span class="prob-badge" style="background:{prob_c}18;color:{prob_c};border:2px solid {prob_c}">{prob*100:.0f}%</span>
                <span class="prob-bar" style="margin-left:8px;font-size:0.85em;color:#6b7280">{bar}</span>
              </div>
              <div class="stake-line">💶 Stake recomendado: {b.get('recommended_stake',0):.2f}€</div>
              <div class="nav-hint">📍 Cómo apostar en Tonybet: {nav}</div>
            </div>
            """, unsafe_allow_html=True)

        if locked_count > 0:
            st.markdown(f"""
            <div class="locked-card">
              🔒 <b>{locked_count} apuesta{'s más' if locked_count > 1 else ' más'}</b>
              disponible{'s' if locked_count > 1 else ''} en Plan Pro
            </div>
            """, unsafe_allow_html=True)
            _upgrade_button(user, "pro", "Desbloquear todas las apuestas — 19€/mes")


# ── TAB 2: Mañana (preview) ───────────────────────────────────────────────────

with tab2:
    if not limits["preview"]:
        st.markdown("""
        <div class="locked-card">
          🔒 <b>Vista previa de mañana</b> disponible en Plan Pro<br>
          <small>Análisis anticipado de los mejores partidos del día siguiente con Claude AI</small>
        </div>
        """, unsafe_allow_html=True)
        _upgrade_button(user, "pro", "Desbloquear Preview — 19€/mes")
    else:
        prev = fetch_json(PREVIEW_URL)
        if not prev:
            st.warning("⏳ Sin datos de mañana todavía.")
            st.link_button("🚀 Generar preview ahora", ACTIONS_URL, use_container_width=True)
        else:
            for_date     = prev.get("for_date", "")
            updated      = prev.get("updated_at", "—")
            total_ev     = prev.get("total_events", 0)
            analyzed     = prev.get("analyzed_count", 0)
            analysis     = prev.get("analysis", "")
            tomorrow_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            today_str_   = datetime.now().strftime("%Y-%m-%d")

            try:
                display_date = datetime.strptime(for_date, "%Y-%m-%d").strftime("%d/%m/%Y")
            except Exception:
                display_date = for_date

            if for_date == tomorrow_str:
                st.success(f"✅ Vista previa actualizada para mañana **{display_date}**")
            elif for_date == today_str_:
                st.warning(f"⚠️ Este preview es de hoy ({display_date}) — se actualizará esta noche.")
            else:
                st.error(f"🔴 Datos desactualizados ({display_date})")
                st.link_button("🚀 Actualizar (GitHub Actions)", ACTIONS_URL, use_container_width=True)

            st.caption(f"Generado: {updated}  ·  {analyzed} de {total_ev} eventos analizados")
            st.markdown("---")
            st.markdown(analysis)


# ── TAB 3: Consultar ─────────────────────────────────────────────────────────

with tab3:
    if not limits["chat"]:
        st.markdown("""
        <div class="locked-card">
          🔒 <b>Chat con Claude</b> disponible en Plan Pro<br>
          <small>Pregunta en lenguaje natural sobre cualquier evento de hoy</small>
        </div>
        """, unsafe_allow_html=True)
        _upgrade_button(user, "pro", "Desbloquear Chat — 19€/mes")
    else:
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

            by_sport: dict[str, int] = {}
            for e in events_raw:
                sp = e.get("deporte") or e.get("sport") or "—"
                by_sport[sp] = by_sport.get(sp, 0) + 1

            st.caption(f"Datos del {updated_ev}  ·  {total_ev} eventos")
            sport_summary = "  ".join(f"{_sport_icon(sp)} {sp} ({n})" for sp, n in sorted(by_sport.items()))
            st.caption(sport_summary)

            # API key: env var > st.secrets > user input
            @st.cache_resource
            def _key_store(): return {"key": ""}
            key_store = _key_store()

            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not api_key:
                try:
                    api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
                except Exception:
                    pass
            if not api_key:
                api_key = key_store.get("key", "") or st.session_state.get("api_key", "")

            if not api_key:
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

            with st.expander("💡 Ejemplos de preguntas"):
                st.markdown(
                    "- ¿Qué partidos hay de La Liga hoy?\n"
                    "- ¿Cuáles son las cuotas del partido de tenis más interesante?\n"
                    "- ¿Hay partidos de la NBA esta noche?\n"
                    "- Dame los 3 partidos con mayor desequilibrio en cuotas\n"
                    "- ¿Qué hay en la NHL hoy y quiénes son los favoritos?"
                )

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

                final_key = api_key or key_store.get("key", "") or st.session_state.get("api_key", "")
                if not final_key:
                    st.error("Introduce tu clave de Anthropic arriba para usar el chat.")
                else:
                    try:
                        import anthropic
                        client      = anthropic.Anthropic(api_key=final_key)
                        events_json = json.dumps(events_raw, ensure_ascii=False)
                        prompt = (
                            f"Eres un asistente experto en apuestas deportivas multideporte. "
                            f"El usuario pregunta: \"{question}\"\n\n"
                            f"Responde usando únicamente los datos disponibles. "
                            f"Sé concreto, claro y organizado. Incluye cuotas cuando las haya. "
                            f"Si no hay eventos que coincidan, dilo claramente.\n\n"
                            f"DATOS ({total_ev} eventos):\n{events_json}"
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

            if st.session_state.get("chat_history"):
                if st.button("🗑️ Limpiar conversación"):
                    st.session_state.chat_history = []
                    st.rerun()


# ── TAB 4: Estadísticas ───────────────────────────────────────────────────────

with tab4:
    st.markdown("### 📊 Mis estadísticas personales")

    if has_supabase:
        try:
            from saas.db import get_user_bets
            all_records = get_user_bets(user["id"], days=30)
        except Exception:
            all_records = []
            st.warning("No se pudo conectar con la base de datos.")
    else:
        log         = fetch_json(f"{GITHUB_RAW}/bets_log.json")
        all_records = log if log else []

    cutoff  = (date.today() - timedelta(days=30)).isoformat()
    recent  = [r for r in all_records if r.get("date", "") >= cutoff]
    settled = [r for r in recent if r.get("result") in ("won", "lost")]
    pending = [r for r in recent if r.get("result") == "pending"]

    if not recent:
        st.info("Sin apuestas registradas en los últimos 30 días.")
        if tier in ("pro", "premium"):
            st.caption("Guarda las apuestas del día desde la pestaña **📋 Hoy** para ver tus estadísticas.")
    else:
        if settled:
            total_stake  = sum(r.get("stake", 0) for r in settled)
            total_profit = sum(r.get("profit", 0) for r in settled)
            won_count    = sum(1 for r in settled if r.get("result") == "won")
            roi          = total_profit / total_stake * 100 if total_stake else 0
            winrate      = won_count / len(settled) * 100
            avg_odds     = sum(r.get("odds", 0) for r in settled) / len(settled)

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
                by_sport_profit[sp] = by_sport_profit.get(sp, 0) + r.get("profit", 0)

            if len(by_sport_profit) > 1:
                import pandas as pd
                st.markdown("**P&L por deporte**")
                df_sport = pd.DataFrame(
                    {"Deporte": list(by_sport_profit.keys()), "P&L (€)": list(by_sport_profit.values())}
                ).sort_values("P&L (€)", ascending=False)
                st.bar_chart(df_sport.set_index("Deporte"))

            # P&L diario
            by_day: dict[str, float] = {}
            for r in settled:
                d = r.get("date", "")
                by_day[d] = by_day.get(d, 0) + r.get("profit", 0)
            if by_day:
                import pandas as pd
                st.markdown("**P&L diario**")
                df = pd.DataFrame(
                    {"Fecha": list(by_day.keys()), "P&L (€)": list(by_day.values())}
                ).sort_values("Fecha")
                st.bar_chart(df.set_index("Fecha"))

            # Historial reciente
            st.markdown("**Historial reciente**")
            for r in sorted(recent, key=lambda x: x.get("date", ""), reverse=True)[:25]:
                icon       = "✅" if r.get("result") == "won" else "❌" if r.get("result") == "lost" else "⏳"
                sp_icon    = _sport_icon(r.get("sport", ""))
                profit_str = f"{r.get('profit', 0):+.2f}€" if r.get("result") in ("won", "lost") else "—"
                st.markdown(
                    f"{icon} {sp_icon} `{r.get('date','')}` **{r.get('event','')}** — "
                    f"{r.get('selection','')} @ {r.get('odds', 0):.2f} "
                    f"(stake {r.get('stake', 0):.2f}€) **{profit_str}**"
                )

        # Marcar resultados pendientes (Pro+)
        if pending:
            st.markdown(f"---\n**Pendientes de resultado:** {len(pending)}")
            can_update = tier in ("pro", "premium") and has_supabase
            for r in pending:
                sp_icon = _sport_icon(r.get("sport", ""))
                bet_id  = r.get("id", "")
                if can_update and bet_id:
                    cols = st.columns([4, 1, 1, 1])
                    cols[0].markdown(
                        f"⏳ {sp_icon} `{r.get('date','')}` {r.get('event','')} — "
                        f"{r.get('selection','')} @ {r.get('odds', 0):.2f}"
                    )
                    for col, result_val, label in (
                        (cols[1], "won",  "✅"),
                        (cols[2], "lost", "❌"),
                        (cols[3], "void", "🚫"),
                    ):
                        if col.button(label, key=f"{result_val}_{bet_id}"):
                            try:
                                from saas.db import update_bet_result
                                update_bet_result(user["id"], bet_id, result_val)
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))
                else:
                    st.markdown(
                        f"⏳ {sp_icon} `{r.get('date','')}` {r.get('event','')} — "
                        f"{r.get('selection','')} @ {r.get('odds', 0):.2f}"
                    )

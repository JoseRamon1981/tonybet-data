"""
Tonybet Betting Advisor — Web Dashboard (Streamlit)
Reads data published to GitHub by the local agent.
"""
import json
from datetime import date, timedelta

import requests
import streamlit as st

GITHUB_RAW = "https://raw.githubusercontent.com/JoseRamon1981/tonybet-data/main"
RECS_URL   = f"{GITHUB_RAW}/recommendations_latest.json"
LOG_URL    = f"{GITHUB_RAW}/bets_log.json"


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
  .bet-card {
    background: #1e1e2e;
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 12px;
    border-left: 4px solid #7c3aed;
  }
  .ev-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 20px;
    font-weight: bold;
    font-size: 0.9em;
  }
  .stat-box {
    background: #1e1e2e;
    border-radius: 10px;
    padding: 14px;
    text-align: center;
  }
</style>
""", unsafe_allow_html=True)


# ── main ─────────────────────────────────────────────────────────────────────

st.title("🎯 Tonybet Advisor")
st.caption("Recomendaciones de apuestas con valor esperado positivo")

tab1, tab2 = st.tabs(["📋 Recomendaciones", "📊 Estadísticas"])


# ── TAB 1: Recomendaciones ────────────────────────────────────────────────────

with tab1:
    data = fetch_json(RECS_URL)

    if not data:
        st.info("No hay recomendaciones publicadas todavía. Ejecuta `python -m tonybet_advisor advisor` en tu PC.")
    else:
        updated = data.get("updated_at", "—")
        bets    = data.get("bets", [])

        st.markdown(f"**Última actualización:** {updated}")

        if not bets:
            st.warning("El agente analizó el mercado y no encontró value bets hoy. Vuelve mañana.")
        else:
            st.success(f"**{len(bets)} value bet(s) encontradas**")

            for b in bets:
                ev  = b.get("expected_value", 0)
                col = ev_color(ev)
                st.markdown(f"""
                <div class="bet-card">
                  <b style="font-size:1.1em">{b.get('event','')}</b><br>
                  <span style="color:#aaa">{b.get('sport','')} · {b.get('market','')}</span>
                  <hr style="border-color:#333; margin:8px 0">
                  <b>Selección:</b> {b.get('selection','')}<br>
                  <b>Cuota:</b> {b.get('odds', 0):.2f} &nbsp;
                  <span class="ev-badge" style="background:{col}20; color:{col}">
                    EV {ev*100:+.1f}%
                  </span><br>
                  <b>Stake recomendado:</b> {b.get('recommended_stake', 0):.2f}€
                </div>
                """, unsafe_allow_html=True)

            total = sum(b.get("recommended_stake", 0) for b in bets)
            st.markdown(f"**Stake total:** {total:.2f}€")


# ── TAB 2: Estadísticas ───────────────────────────────────────────────────────

with tab2:
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

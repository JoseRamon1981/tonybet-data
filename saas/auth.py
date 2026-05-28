"""Supabase authentication helpers for Streamlit."""
import os
import streamlit as st


def _get_supabase():
    from supabase import create_client
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_ANON_KEY"],
    )


def _load_tier(user_id: str) -> str:
    try:
        from saas.db import get_user_profile
        return get_user_profile(user_id).get("subscription_tier", "free")
    except Exception:
        return "free"


def require_auth() -> tuple[dict | None, str]:
    """
    Ensure user is authenticated. Shows login/register page if not.
    Returns (user_dict, tier) or (None, '') if not authenticated.
    """
    user = st.session_state.get("supabase_user")
    if user:
        tier = st.session_state.get("subscription_tier", "free")
        return user, tier

    _render_auth_page()
    return None, ""


def _render_auth_page():
    st.markdown("## 🎯 Tonybet Advisor")
    st.markdown("##### Sistema de value betting con IA — todos los deportes")
    st.markdown("---")

    tab_login, tab_register = st.tabs(["Iniciar sesión", "Crear cuenta"])
    supabase = _get_supabase()

    with tab_login:
        email    = st.text_input("Email", key="login_email")
        password = st.text_input("Contraseña", type="password", key="login_password")
        if st.button("Entrar", type="primary", use_container_width=True):
            try:
                resp = supabase.auth.sign_in_with_password({"email": email, "password": password})
                user = {"id": resp.user.id, "email": resp.user.email}
                st.session_state["supabase_user"]    = user
                st.session_state["subscription_tier"] = _load_tier(user["id"])
                st.rerun()
            except Exception as e:
                st.error(f"Error de acceso: {e}")

    with tab_register:
        email    = st.text_input("Email", key="reg_email")
        password = st.text_input("Contraseña (mín. 8 caracteres)", type="password", key="reg_password")
        if st.button("Crear cuenta gratuita", type="primary", use_container_width=True):
            try:
                resp = supabase.auth.sign_up({"email": email, "password": password})
                if resp.user:
                    st.success("Cuenta creada. Revisa tu email para confirmar y luego inicia sesión.")
                else:
                    st.error("No se pudo crear la cuenta. Inténtalo de nuevo.")
            except Exception as e:
                st.error(f"Error al registrar: {e}")

    st.markdown("---")
    st.caption("Plan gratuito: accede a las primeras 2 recomendaciones del día · Sin tarjeta de crédito")


def render_sidebar(user: dict, tier: str):
    """Render sidebar with user info, subscription tier and upgrade CTA."""
    with st.sidebar:
        username = user["email"].split("@")[0]
        st.markdown(f"### Hola, {username}")

        tier_styles = {
            "free":    ("🆓 Plan Gratuito", "#6b7280"),
            "pro":     ("⭐ Plan Pro",       "#ca8a04"),
            "premium": ("💎 Plan Premium",   "#7c3aed"),
        }
        label, color = tier_styles.get(tier, tier_styles["free"])
        st.markdown(
            f"<span style='color:{color};font-weight:700;font-size:1.05em'>{label}</span>",
            unsafe_allow_html=True,
        )
        st.markdown("---")

        if tier == "free":
            st.markdown("**Desbloquea con Pro:**")
            st.markdown("✅ Todas las apuestas del día")
            st.markdown("✅ Chat con Claude sobre eventos")
            st.markdown("✅ Preview de partidos de mañana")
            st.markdown("✅ Estadísticas personales")
            try:
                from saas.billing import create_checkout_url
                url = create_checkout_url(user["id"], user["email"], "pro")
                if url:
                    st.link_button(
                        "Upgrade a Pro — 19€/mes", url,
                        use_container_width=True, type="primary",
                    )
            except Exception:
                pass

        elif tier == "pro":
            try:
                from saas.billing import create_checkout_url
                url = create_checkout_url(user["id"], user["email"], "premium")
                if url:
                    st.link_button("Upgrade a Premium — 49€/mes", url, use_container_width=True)
            except Exception:
                pass

        st.markdown("---")
        if st.button("Cerrar sesión", use_container_width=True):
            _logout()


def _logout():
    try:
        _get_supabase().auth.sign_out()
    except Exception:
        pass
    for key in ("supabase_user", "subscription_tier", "api_key", "chat_history"):
        st.session_state.pop(key, None)
    st.rerun()

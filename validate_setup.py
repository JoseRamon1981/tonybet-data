"""
Tonybet Advisor SaaS — Script de validación de configuración.
Ejecutar: python validate_setup.py
"""
import os
import sys

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

ok    = lambda msg: print(f"  {GREEN}✓{RESET} {msg}")
fail  = lambda msg: print(f"  {RED}✗{RESET} {msg}")
warn  = lambda msg: print(f"  {YELLOW}⚠{RESET} {msg}")
header = lambda msg: print(f"\n{BOLD}{msg}{RESET}")


def check_env(name: str, prefix: str = "", required: bool = True) -> str:
    val = os.environ.get(name, "")
    if not val:
        if required:
            fail(f"{name} — no configurada")
        else:
            warn(f"{name} — opcional, no configurada")
        return ""
    if prefix and not val.startswith(prefix):
        fail(f"{name} — formato incorrecto (debe empezar por '{prefix}')")
        return ""
    ok(f"{name} = {val[:30]}...")
    return val


def check_supabase(url: str, anon_key: str, service_key: str) -> bool:
    if not url or not anon_key:
        return False
    try:
        from supabase import create_client
        sb = create_client(url, anon_key)
        # Test: ping the health endpoint
        import requests
        r = requests.get(f"{url}/rest/v1/", headers={"apikey": anon_key}, timeout=5)
        if r.status_code in (200, 401):
            ok("Supabase: conexión establecida")
            return True
        fail(f"Supabase: respuesta inesperada ({r.status_code})")
        return False
    except ImportError:
        warn("supabase-py no instalado — ejecuta: pip install supabase")
        return False
    except Exception as e:
        fail(f"Supabase: {e}")
        return False


def check_stripe(secret_key: str, price_pro: str, price_premium: str) -> bool:
    if not secret_key:
        return False
    try:
        import stripe
        stripe.api_key = secret_key
        # Verify key by listing a tiny amount of products
        products = stripe.Product.list(limit=1)
        ok(f"Stripe: conexión OK ({'TEST' if 'test' in secret_key else 'LIVE'} mode)")
        if price_pro:
            try:
                stripe.Price.retrieve(price_pro)
                ok(f"Stripe: precio Pro encontrado ({price_pro[:20]}...)")
            except Exception:
                fail(f"Stripe: precio Pro no encontrado ({price_pro})")
        if price_premium:
            try:
                stripe.Price.retrieve(price_premium)
                ok(f"Stripe: precio Premium encontrado ({price_premium[:20]}...)")
            except Exception:
                fail(f"Stripe: precio Premium no encontrado ({price_premium})")
        return True
    except ImportError:
        warn("stripe no instalado — ejecuta: pip install stripe")
        return False
    except Exception as e:
        fail(f"Stripe: {e}")
        return False


def check_anthropic(api_key: str) -> bool:
    if not api_key:
        return False
    try:
        import anthropic
        client   = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": "Hi"}],
        )
        ok("Anthropic API: conexión OK")
        return True
    except ImportError:
        warn("anthropic no instalado — ejecuta: pip install anthropic")
        return False
    except Exception as e:
        fail(f"Anthropic API: {e}")
        return False


def check_odds_api(api_key: str) -> bool:
    if not api_key:
        warn("ODDS_API_KEY no configurada — el advisor usará el scraper como fallback")
        return False
    try:
        import requests
        r = requests.get(
            "https://api.the-odds-api.com/v4/sports",
            params={"apiKey": api_key},
            timeout=5,
        )
        if r.status_code == 200:
            remaining = r.headers.get("x-requests-remaining", "?")
            ok(f"The Odds API: OK — {remaining} requests restantes este mes")
            return True
        fail(f"The Odds API: error {r.status_code} — clave inválida o cuota agotada")
        return False
    except Exception as e:
        fail(f"The Odds API: {e}")
        return False


def main():
    print(f"\n{BOLD}{'='*50}")
    print(" Tonybet Advisor — Validación de configuración")
    print(f"{'='*50}{RESET}")

    errors = 0

    # ── Variables de entorno ──────────────────────────────────────────────────
    header("1. Variables de entorno")

    supabase_url      = check_env("SUPABASE_URL",      "https://")
    supabase_anon     = check_env("SUPABASE_ANON_KEY", "sb_publishable_")
    supabase_service  = check_env("SUPABASE_SERVICE_KEY", "sb_secret_", required=False)
    stripe_key        = check_env("STRIPE_SECRET_KEY", "sk_")
    stripe_price_pro  = check_env("STRIPE_PRICE_PRO",  "price_")
    stripe_price_prem = check_env("STRIPE_PRICE_PREMIUM", "price_")
    app_url           = check_env("APP_URL",            "http", required=False)
    anthropic_key     = check_env("ANTHROPIC_API_KEY", "sk-ant")
    odds_api_key      = check_env("ODDS_API_KEY",       required=False)

    if not supabase_url:  errors += 1
    if not stripe_key:    errors += 1
    if not anthropic_key: errors += 1

    # ── Conectividad ──────────────────────────────────────────────────────────
    header("2. Conectividad con servicios")

    if supabase_url:
        if not check_supabase(supabase_url, supabase_anon, supabase_service):
            errors += 1

    if stripe_key:
        if not check_stripe(stripe_key, stripe_price_pro, stripe_price_prem):
            errors += 1

    if anthropic_key:
        if not check_anthropic(anthropic_key):
            errors += 1

    check_odds_api(odds_api_key)

    # ── Resultado ─────────────────────────────────────────────────────────────
    header("3. Resultado")

    if errors == 0:
        print(f"\n  {GREEN}{BOLD}Todo OK — la app está lista para desplegarse.{RESET}")
        print(f"  Recuerda añadir estas variables en Railway antes del deploy.\n")
    else:
        print(f"\n  {RED}{BOLD}{errors} error(es) encontrado(s).{RESET}")
        print(f"  Revisa los puntos marcados con ✗ y consulta SETUP.md.\n")
        sys.exit(1)


if __name__ == "__main__":
    # Load .env if present
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    main()

"""
Playwright scraper: logs into Tonybet and captures betting events by
intercepting the internal JSON API responses the browser loads.
"""
import asyncio
import json
import re
from typing import Any

from playwright.async_api import async_playwright, Page, Response

from .config import config


# ── helpers ──────────────────────────────────────────────────────────────────

def _is_odds_response(url: str) -> bool:
    patterns = [
        r"/api/",
        r"/sports",
        r"/prematch",
        r"/odds",
        r"/events",
        r"/markets",
        r"/lines",
    ]
    return any(re.search(p, url, re.IGNORECASE) for p in patterns)


def _parse_generic_event(raw: Any) -> list[dict]:
    """
    Best-effort parser for Tonybet JSON responses.
    Returns a flat list of event dicts regardless of nesting.
    """
    events: list[dict] = []

    if isinstance(raw, list):
        for item in raw:
            events.extend(_parse_generic_event(item))
        return events

    if not isinstance(raw, dict):
        return events

    # Try to detect event-like objects
    has_name = "name" in raw or "eventName" in raw or "title" in raw
    has_odds = any(k in raw for k in ("odds", "markets", "outcomes", "selections"))

    if has_name and has_odds:
        event = {
            "id": raw.get("id") or raw.get("eventId") or "",
            "name": raw.get("name") or raw.get("eventName") or raw.get("title") or "Unknown",
            "sport": raw.get("sport") or raw.get("sportName") or raw.get("category") or "Unknown",
            "competition": raw.get("competition") or raw.get("league") or raw.get("tournament") or "",
            "starts_at": raw.get("startTime") or raw.get("startsAt") or raw.get("date") or "",
            "markets": _extract_markets(raw),
        }
        if event["markets"]:
            events.append(event)
        return events

    # Recurse into nested structures
    for value in raw.values():
        if isinstance(value, (dict, list)):
            events.extend(_parse_generic_event(value))

    return events


def _extract_markets(raw: dict) -> list[dict]:
    markets = []
    candidates = raw.get("markets") or raw.get("odds") or raw.get("outcomes") or []

    if isinstance(candidates, dict):
        candidates = list(candidates.values())

    for m in candidates:
        if not isinstance(m, dict):
            continue
        selections = m.get("selections") or m.get("outcomes") or m.get("runners") or []
        if isinstance(selections, dict):
            selections = list(selections.values())

        parsed_sels = []
        for s in selections:
            if isinstance(s, dict):
                odds_val = s.get("odds") or s.get("price") or s.get("decimal") or s.get("value")
                try:
                    odds_val = float(odds_val)
                except (TypeError, ValueError):
                    continue
                if odds_val < 1.01:
                    continue
                parsed_sels.append({
                    "name": s.get("name") or s.get("label") or s.get("outcome") or "Unknown",
                    "odds": odds_val,
                })

        if parsed_sels:
            markets.append({
                "name": m.get("name") or m.get("type") or m.get("marketName") or "Main",
                "selections": parsed_sels,
            })

    return markets


# ── main scraper ──────────────────────────────────────────────────────────────

class TonybetScraper:
    def __init__(self):
        self._raw_payloads: list[Any] = []

    async def _capture_response(self, response: Response) -> None:
        if not _is_odds_response(response.url):
            return
        if response.status != 200:
            return
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type:
            return
        try:
            data = await response.json()
            self._raw_payloads.append(data)
        except Exception:
            pass

    async def _try_login(self, page: Page) -> bool:
        """Attempt login — returns True if successful, False if skipped/failed."""
        if not config.tonybet_username or not config.tonybet_password:
            print("  ⚠ Sin credenciales — accediendo sin sesión (cuotas públicas disponibles)")
            return False

        try:
            print("  → Intentando login…")
            # Try multiple login button patterns
            patterns = [
                page.get_by_role("button", name=re.compile(r"log.?in|sign.?in|iniciar|entrar|acceder", re.I)),
                page.get_by_role("link",   name=re.compile(r"log.?in|sign.?in|iniciar|entrar|acceder", re.I)),
                page.locator("a, button, span").filter(has_text=re.compile(r"^(log.?in|sign.?in|iniciar|entrar)$", re.I)),
                page.locator("[class*='login' i], [class*='signin' i]"),
                page.locator("[data-test*='login' i], [data-testid*='login' i]"),
            ]
            login_btn = None
            for pat in patterns:
                try:
                    if await pat.count() > 0:
                        login_btn = pat.first
                        break
                except Exception:
                    continue

            if not login_btn:
                print("  ⚠ Botón de login no encontrado — accediendo sin sesión")
                return False

            await login_btn.click(timeout=10_000)
            await page.wait_for_timeout(1500)

            await page.get_by_placeholder(re.compile(r"email|user|usuario", re.I)).fill(config.tonybet_username, timeout=10_000)
            await page.get_by_placeholder(re.compile(r"password|contraseña", re.I)).fill(config.tonybet_password, timeout=10_000)
            await page.get_by_role("button", name=re.compile(r"log.?in|sign.?in|entrar|acceder", re.I)).click(timeout=10_000)
            await page.wait_for_timeout(3000)
            print("  ✓ Sesión iniciada")
            return True

        except Exception as e:
            print(f"  ⚠ Login omitido ({e.__class__.__name__}) — accediendo sin sesión")
            return False

    async def scrape(self) -> list[dict]:
        print("Iniciando scraper de Tonybet…")
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=config.headless,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="es-ES",
            )
            page = await context.new_page()
            page.on("response", lambda r: asyncio.ensure_future(self._capture_response(r)))

            # Open Tonybet home first, then optionally login
            print("  → Abriendo Tonybet…")
            await page.goto(f"{config.tonybet_url}/en", wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            await self._try_login(page)

            # Navigate to prematch section and wait for data to load
            # "networkidle" times out on TonyBet (persistent background requests)
            print("  → Cargando apuestas disponibles…")
            await page.goto(
                f"{config.tonybet_url}/en/prematch",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            await page.wait_for_timeout(6000)  # extra wait for JS to load odds

            # Scroll to trigger lazy-loaded content
            for _ in range(3):
                await page.mouse.wheel(0, 1500)
                await page.wait_for_timeout(1500)

            await browser.close()

        # Parse collected payloads
        events: list[dict] = []
        for payload in self._raw_payloads:
            events.extend(_parse_generic_event(payload))

        # Deduplicate by event id
        seen: set[str] = set()
        unique: list[dict] = []
        for e in events:
            key = str(e.get("id") or e.get("name"))
            if key not in seen:
                seen.add(key)
                unique.append(e)

        print(f"  ✓ {len(unique)} eventos encontrados")
        return unique

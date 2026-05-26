"""
Playwright scraper: logs into Tonybet and captures betting events by
intercepting the internal JSON API responses the browser loads.
Falls back to DOM extraction if no JSON is captured.
"""
import asyncio
import json
import re
from typing import Any

from playwright.async_api import async_playwright, Page, Response

from .config import config


# ── helpers ──────────────────────────────────────────────────────────────────

def _is_odds_response(url: str) -> bool:
    # Skip obvious non-data URLs (analytics, tracking, fonts, images, auth tokens)
    skip_patterns = [
        r"google-analytics", r"googletagmanager", r"facebook\.com",
        r"hotjar", r"zendesk", r"intercom", r"sentry",
        r"\.woff", r"\.ttf", r"\.png", r"\.jpg", r"\.svg",
        r"/token", r"/auth/", r"/oauth",
    ]
    if any(re.search(p, url, re.IGNORECASE) for p in skip_patterns):
        return False
    # Accept everything else — let content-type + parser do the real filtering
    return True


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


def _parse_dom_events(dom_data: dict) -> list[dict]:
    """
    Convert raw DOM extraction result into our event format.
    Used as fallback when no JSON API responses are captured.
    """
    events = []
    raw_events = dom_data.get("events", [])
    print(f"  → DOM fallback: {len(raw_events)} bloques candidatos encontrados")

    for i, block in enumerate(raw_events):
        text = block.get("text", "")
        odds_list = block.get("odds", [])
        name = block.get("name", "")
        sport = block.get("sport", "Unknown")
        competition = block.get("competition", "")

        if not name or len(odds_list) < 1:
            continue

        # Build a simple 1X2 or Match Winner market from extracted odds
        selections = []
        labels = block.get("labels", [])
        for j, odd in enumerate(odds_list[:3]):
            label = labels[j] if j < len(labels) else ["1", "X", "2"][j] if j < 3 else f"Sel{j+1}"
            selections.append({"name": label, "odds": odd})

        if selections:
            events.append({
                "id": f"dom_{i}",
                "name": name,
                "sport": sport,
                "competition": competition,
                "starts_at": block.get("starts_at", ""),
                "markets": [{"name": "Match Winner", "selections": selections}],
            })

    return events


# ── main scraper ──────────────────────────────────────────────────────────────

class TonybetScraper:
    def __init__(self):
        self._raw_payloads: list[Any] = []
        self._captured_urls: list[str] = []

    async def _capture_response(self, response: Response) -> None:
        if not _is_odds_response(response.url):
            return
        if response.status != 200:
            return
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type:
            return
        try:
            body = await response.body()
            if len(body) < 200:  # skip tiny JSON (pings, acks)
                return
            data = await response.json()
            self._raw_payloads.append(data)
            self._captured_urls.append(response.url)
        except Exception:
            pass

    async def _dismiss_cookie_banner(self, page: Page) -> None:
        """Dismiss GDPR/cookie consent banners — mandatory on EU betting sites."""
        selectors = [
            "button:has-text('Accept all')",
            "button:has-text('Accept All')",
            "button:has-text('Aceptar todo')",
            "button:has-text('Aceptar')",
            "button:has-text('I agree')",
            "button:has-text('Agree')",
            "button:has-text('OK')",
            "[class*='cookie'] button[class*='accept' i]",
            "[class*='consent'] button[class*='accept' i]",
            "[id*='cookie'] button",
            "[id*='consent'] button",
            "#onetrust-accept-btn-handler",
            ".cc-btn.cc-allow",
        ]
        for sel in selectors:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0:
                    await btn.click(timeout=3000)
                    print("  ✓ Banner de cookies cerrado")
                    await page.wait_for_timeout(1000)
                    return
            except Exception:
                continue

        # JavaScript fallback
        try:
            clicked = await page.evaluate("""() => {
                const accept_words = ['accept all', 'aceptar', 'i agree', 'agree', 'allow all', 'ok', 'got it'];
                const btns = [...document.querySelectorAll('button, a[role=button]')];
                for (const b of btns) {
                    const t = (b.textContent || '').trim().toLowerCase();
                    if (accept_words.some(w => t.includes(w)) && t.length < 25) {
                        b.click();
                        return t;
                    }
                }
                return null;
            }""")
            if clicked:
                print(f"  ✓ Banner cerrado via JS: '{clicked}'")
                await page.wait_for_timeout(1000)
        except Exception:
            pass

    async def _try_login(self, page: Page) -> bool:
        """Attempt login — returns True if successful, False if skipped/failed."""
        if not config.tonybet_username or not config.tonybet_password:
            print("  ⚠ Sin credenciales — accediendo sin sesión (cuotas públicas disponibles)")
            return False

        try:
            print("  → Intentando login…")

            # Strategy 1: standard locator patterns
            patterns = [
                page.get_by_role("button", name=re.compile(r"log.?in|sign.?in|iniciar|entrar|acceder", re.I)),
                page.get_by_role("link",   name=re.compile(r"log.?in|sign.?in|iniciar|entrar|acceder", re.I)),
                page.locator("a, button, span").filter(has_text=re.compile(r"^(log.?in|sign.?in|iniciar|entrar)$", re.I)),
                page.locator("[class*='login' i], [class*='signin' i]").first,
                page.locator("[data-test*='login' i], [data-testid*='login' i]").first,
                page.locator("header a, header button").filter(has_text=re.compile(r"log|sign|entra", re.I)),
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
                # Strategy 2: JavaScript fallback — click any element with login-related text
                clicked = await page.evaluate("""() => {
                    const keywords = ['login', 'log in', 'sign in', 'iniciar', 'entrar', 'acceder'];
                    const els = [...document.querySelectorAll('a, button, span[role], div[role=button]')];
                    for (const el of els) {
                        const txt = (el.textContent || '').trim().toLowerCase();
                        if (keywords.some(k => txt.includes(k)) && txt.length < 30) {
                            el.click();
                            return el.textContent.trim();
                        }
                    }
                    return null;
                }""")
                if clicked:
                    print(f"  → Botón encontrado via JS: '{clicked}'")
                    await page.wait_for_timeout(1500)
                else:
                    print("  ⚠ Botón de login no encontrado — accediendo sin sesión")
                    return False
            else:
                await login_btn.click(timeout=10_000)
                await page.wait_for_timeout(1500)

            # Fill credentials
            try:
                await page.get_by_placeholder(re.compile(r"email|user|usuario|login", re.I)).first.fill(config.tonybet_username, timeout=8_000)
                await page.get_by_placeholder(re.compile(r"password|contraseña|pass", re.I)).first.fill(config.tonybet_password, timeout=8_000)
            except Exception:
                # Fallback: fill by input type via JavaScript
                await page.evaluate(f"""() => {{
                    const inputs = document.querySelectorAll('input');
                    for (const inp of inputs) {{
                        const t = inp.type.toLowerCase();
                        if (t === 'email' || t === 'text') {{
                            inp.value = '{config.tonybet_username}';
                            inp.dispatchEvent(new Event('input', {{bubbles:true}}));
                        }}
                        if (t === 'password') {{
                            inp.value = '{config.tonybet_password}';
                            inp.dispatchEvent(new Event('input', {{bubbles:true}}));
                        }}
                    }}
                }}""")
                await page.wait_for_timeout(500)

            # Submit
            try:
                await page.get_by_role("button", name=re.compile(r"log.?in|sign.?in|entrar|acceder|submit", re.I)).click(timeout=8_000)
            except Exception:
                await page.keyboard.press("Enter")

            await page.wait_for_timeout(3500)
            print("  ✓ Sesión iniciada")
            return True

        except Exception as e:
            print(f"  ⚠ Login omitido ({e.__class__.__name__}) — accediendo sin sesión")
            return False

    async def _scrape_dom(self, page: Page) -> list[dict]:
        """
        DOM fallback: extract events directly from rendered HTML when no JSON is captured.
        Uses JavaScript to find event blocks with odds patterns.
        """
        print("  → Fallback: extrayendo datos del DOM…")
        try:
            await page.goto(
                f"{config.tonybet_url}/en/prematch",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            await page.wait_for_timeout(5000)
            await self._dismiss_cookie_banner(page)
            await page.wait_for_timeout(2000)

            # Scroll to load content
            for _ in range(8):
                await page.mouse.wheel(0, 1500)
                await page.wait_for_timeout(600)

            dom_data = await page.evaluate("""() => {
                const oddsRe = /^\\d{1,2}\\.\\d{2}$/;
                const results = [];

                // Common TonyBet / generic betting site selectors
                const rowSelectors = [
                    '[class*="event-row"]', '[class*="EventRow"]',
                    '[class*="match-row"]', '[class*="MatchRow"]',
                    '[class*="game-row"]', '[class*="sport-event"]',
                    '[class*="prematch-event"]', '[class*="event-item"]',
                    'li[class*="event"]', 'tr[class*="event"]',
                    '[data-event-id]', '[data-match-id]',
                ];

                let rows = [];
                for (const sel of rowSelectors) {
                    const found = [...document.querySelectorAll(sel)];
                    if (found.length > 2) { rows = found; break; }
                }

                // Fallback: look for elements containing VS or vs with odds nearby
                if (rows.length === 0) {
                    const allEls = [...document.querySelectorAll('*')];
                    rows = allEls.filter(el => {
                        const t = el.innerText || '';
                        return (t.includes(' vs ') || t.includes(' - ')) &&
                               t.length > 10 && t.length < 300 &&
                               el.querySelectorAll('*').length < 40;
                    });
                }

                for (const row of rows.slice(0, 80)) {
                    const text = (row.innerText || '').trim();
                    if (!text || text.length > 400) continue;

                    // Find all numeric odds-like values in child elements
                    const spans = [...row.querySelectorAll('span, button, div')];
                    const oddsEls = spans.filter(s => oddsRe.test((s.innerText || '').trim()));
                    const oddsVals = oddsEls.map(s => parseFloat(s.innerText.trim()))
                                           .filter(v => v >= 1.01 && v <= 50);

                    if (oddsVals.length < 1) continue;

                    // Try to find event name: look for "Team A vs Team B" or "Player, A vs Player, B"
                    const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
                    let name = '';
                    for (const line of lines) {
                        if ((line.includes(' vs ') || line.includes(' - ')) && line.length > 5 && line.length < 100) {
                            name = line;
                            break;
                        }
                    }
                    if (!name && lines.length > 0) name = lines[0];
                    if (!name) continue;

                    // Extract odds labels (1, X, 2 or team names)
                    const labels = oddsEls.map(el => {
                        const prev = el.previousElementSibling;
                        return prev ? (prev.innerText || '').trim() : '';
                    });

                    // Guess sport from surrounding context
                    let sport = 'Unknown';
                    const ctx = (row.closest('[class*="sport"]') || row.closest('[class*="category"]') || {});
                    const ctxText = ((ctx.innerText || ctx.className || '') + '').toLowerCase();
                    if (ctxText.includes('tennis') || ctxText.includes('tenis')) sport = 'Tenis';
                    else if (ctxText.includes('football') || ctxText.includes('soccer') || ctxText.includes('futbol')) sport = 'Futbol';
                    else if (ctxText.includes('basketball') || ctxText.includes('baloncesto')) sport = 'Baloncesto';
                    else if (ctxText.includes('hockey')) sport = 'Hockey';

                    results.push({ name, sport, labels, odds: oddsVals, starts_at: '', competition: '' });
                }

                return {
                    title: document.title,
                    url: window.location.href,
                    events: results,
                };
            }""")

            print(f"  → DOM: título='{dom_data.get('title', '')}' url='{dom_data.get('url', '')}'")
            return _parse_dom_events(dom_data)

        except Exception as e:
            print(f"  ⚠ Fallback DOM falló: {e}")
            return []

    async def scrape(self) -> list[dict]:
        print("Iniciando scraper de Tonybet…")
        page_ref: list[Page] = []  # keep page alive for DOM fallback

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

            # Open Tonybet home first, dismiss cookie banner, then optionally login
            print("  → Abriendo Tonybet…")
            await page.goto(f"{config.tonybet_url}/en", wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            await self._dismiss_cookie_banner(page)
            await page.wait_for_timeout(1000)
            await self._try_login(page)

            # Navigate to prematch section
            print("  → Cargando apuestas disponibles…")
            await page.goto(
                f"{config.tonybet_url}/en/prematch",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            await page.wait_for_timeout(8000)  # extra wait for JS to load odds

            # Scroll to trigger lazy-loaded content
            for _ in range(5):
                await page.mouse.wheel(0, 2000)
                await page.wait_for_timeout(1500)

            # Also navigate to specific sport sections to trigger API calls
            for sport_path in ["/en/prematch/tennis", "/en/prematch/football"]:
                try:
                    await page.goto(
                        f"{config.tonybet_url}{sport_path}",
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )
                    await page.wait_for_timeout(4000)
                    for _ in range(3):
                        await page.mouse.wheel(0, 1500)
                        await page.wait_for_timeout(1000)
                except Exception:
                    pass

            # If no JSON captured, try DOM extraction before closing browser
            dom_events: list[dict] = []
            if not self._raw_payloads:
                dom_events = await self._scrape_dom(page)

            await browser.close()

        # Debug: show what JSON URLs were captured
        if self._captured_urls:
            print(f"  → {len(self._captured_urls)} respuestas JSON capturadas")
            for url in self._captured_urls[:8]:
                print(f"     {url[:120]}")
        else:
            print("  ⚠ Ninguna respuesta JSON capturada")

        # Parse collected JSON payloads
        events: list[dict] = []
        for payload in self._raw_payloads:
            events.extend(_parse_generic_event(payload))

        # Use DOM events as fallback if JSON gave nothing
        if not events and dom_events:
            print(f"  → Usando {len(dom_events)} eventos extraídos del DOM")
            events = dom_events

        # Deduplicate by event id / name
        seen: set[str] = set()
        unique: list[dict] = []
        for e in events:
            key = str(e.get("id") or e.get("name"))
            if key not in seen:
                seen.add(key)
                unique.append(e)

        print(f"  ✓ {len(unique)} eventos encontrados")
        return unique
